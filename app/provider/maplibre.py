"""OGC API Maps drawn by a renderer in its own process.

The provider composes the pieces of :mod:`app.maps.contract`: the source
of the collection, its styles and a renderer. Today the source is a
PMTiles archive and the styles are MapLibre's. The renderer reads the
data itself, through the URL the style carries.

The provider owns one renderer, built at the first map, and keeps the
renderer's C++ engine out of the web worker. Requests wait for it behind
a semaphore, in a queue of limited length; a render that takes too long
or fails replaces the renderer.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import math
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path
from typing import Any, ClassVar

from pygeoapi.provider.base import BaseProvider, ProviderGenericError, ProviderItemNotFoundError

from app.config.logging import create_logger
from app.maps.camera import HALF_WORLD
from app.maps.contract import MapRenderer, MapRequest, MapSource, MapStyles, SourceNotDrawableError
from app.maps.sources import ObjectUrl, SourceContext, source_for
from app.maps.styles import MapLibreStyles
from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from app.provider.storage import load_store, split_source

logger = create_logger("app.provider.maplibre")

WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
"""The only CRS the renderer draws in."""

_MAPS = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf"

DEFAULTS: dict[str, Any] = {
    # The collection page of pygeoapi asks for an image as wide as its map.
    "max_size": 2048,
    "queue": 8,
    "timeout": 30,
    # Seconds a render may go on after its map answered 504; four times
    # the timeout when unset.
    "render_limit": None,
    "max_rss_mb": 600,
    "sign_ttl": 3600,
    "styles": {},
    "default_style": None,
    "source": "archive",
    "archive_url": None,
    "renderer": "app.maps.mlnative.create_renderer",
}


class _MapError(ProviderGenericError):
    """A map error whose message, when none is given, is its ``default_msg``.

    pygeoapi's errors pass ``msg`` on to the exception, so one raised
    without a message logs as ``None``.
    """

    def __init__(self, msg: str | None = None, *args: Any, user_msg: str | None = None) -> None:
        super().__init__(msg or user_msg or self.default_msg, *args, user_msg=user_msg)


class MapParameterError(_MapError):
    """A map parameter this server cannot honour."""

    ogc_exception_code = "InvalidParameterValue"
    http_status_code = HTTPStatus.BAD_REQUEST
    default_msg = "invalid map parameter"


class MapTooLargeError(MapParameterError):
    """A width or height above ``max_size``: OGC API - Maps prefers a 413 for it."""

    http_status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    default_msg = "the map is larger than this server draws"


class MapRendererBusyError(_MapError):
    """Too many maps are already waiting for the renderer."""

    http_status_code = HTTPStatus.SERVICE_UNAVAILABLE
    default_msg = "the map renderer is busy, retry later"
    # Seconds for the Retry-After header: a warm map takes well under one, the
    # first map of a small area from 2 to 9.
    retry_after = 5


class MapRenderTimeoutError(_MapError):
    """The renderer took longer than the configured timeout."""

    http_status_code = HTTPStatus.GATEWAY_TIMEOUT
    default_msg = "the map took too long to render"


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no")
    return bool(value)


def _clamp(value: float) -> float:
    if math.isnan(value):
        return value
    return max(-HALF_WORLD, min(HALF_WORLD, value))


def _load_factory(dotted: str):
    module_name, _, name = dotted.rpartition(".")
    try:
        return getattr(importlib.import_module(module_name), name)
    except (ImportError, AttributeError) as error:
        raise ProviderGenericError(
            user_msg=(
                f"map rendering is not available: {dotted} could not be loaded; "
                "install the maps dependency group"
            )
        ) from error


class MapLibreMapProvider(AsyncProviderMixin, StorageBackedMixin, BaseProvider):
    """A map provider over a PMTiles archive, drawn with MapLibre styles."""

    THREAD_SAFE = True
    native_async = True
    conformance_classes: ClassVar[tuple[str, ...]] = (
        f"{_MAPS}/core",
        f"{_MAPS}/collection-map",
        f"{_MAPS}/png",
        f"{_MAPS}/scaling",
        f"{_MAPS}/spatial-subsetting",
        f"{_MAPS}/background",
    )

    def __init__(self, provider_def: dict) -> None:
        """Read the options; no I/O happens until the first map."""
        super().__init__(provider_def)
        self.options = {**DEFAULTS, **(provider_def.get("options") or {})}
        storage_crs = provider_def.get("storage_crs", WEB_MERCATOR)
        if storage_crs != WEB_MERCATOR:
            raise ProviderGenericError(
                user_msg=f"the map provider draws in {WEB_MERCATOR}, not in {storage_crs}"
            )
        try:
            self._source_format = source_for(provider_def["data"])
        except LookupError as error:
            raise ProviderGenericError(user_msg=f"map source not supported: {error}") from None
        # The renderer fetches the archive with plain HTTP. A public bucket
        # read without signatures has no URL to sign, and obstore would
        # first spend seconds looking for credentials.
        store_options = provider_def.get("store_options") or {}
        if (
            store_options.get("skip_signature")
            and not self.options["archive_url"]
            and self._is_bucket(provider_def["data"])
        ):
            raise ProviderGenericError(
                user_msg="a public bucket needs options.archive_url, the https URL of the archive"
            )
        self._renderer: MapRenderer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._semaphore: asyncio.Semaphore | None = None
        self._waiting = 0
        self._map_styles: MapStyles | None = None
        self._closing: set[asyncio.Task] = set()
        self._drawing: set[asyncio.Task] = set()
        self._closed = False

    @property
    def renderer_is_built(self) -> bool:
        """Whether a renderer is currently alive."""
        return self._renderer is not None

    @property
    def waiting(self) -> int:
        """How many maps are being drawn or are waiting for the renderer."""
        return self._waiting

    def style_names(self) -> list[str]:
        """The configured style names."""
        return sorted(self.options["styles"])

    @staticmethod
    def _is_bucket(data: str) -> bool:
        return "://" in data and not data.startswith(("file://", "http://", "https://"))

    def _object_url(self) -> ObjectUrl:
        data = self.provider_def["data"]
        if self.options["archive_url"]:
            return ObjectUrl(public_url=self.options["archive_url"])
        if data.startswith(("http://", "https://")):
            return ObjectUrl(public_url=data)
        if not self._is_bucket(data):
            return ObjectUrl(local_path=Path(data.removeprefix("file://")))
        return ObjectUrl(signer=self._sign, ttl=timedelta(seconds=self.options["sign_ttl"]))

    def _sign(self, ttl: timedelta) -> str:
        try:
            return self.signed_url(ttl)
        except Exception as error:
            logger.warning(f"could not sign the archive URL: {type(error).__name__}")
            raise ProviderGenericError(user_msg="the archive URL could not be signed") from None

    def _source(self) -> MapSource:
        context = SourceContext(
            data=self.provider_def["data"],
            options=self.options,
            location=self._object_url,
            ranges=lambda: self.byte_ranges().read,
        )
        return self._source_format.build(context)

    def _read_style(self, location: str) -> dict:
        if "://" not in location:
            return json.loads(Path(location).read_text())
        base, key = split_source(location)
        return json.loads(load_store(base, self.provider_def.get("store_options")).get(key))

    def _styles(self) -> MapStyles:
        if self._map_styles is None:
            self._map_styles = MapLibreStyles(
                self._source(),
                {name: self._read_style(where) for name, where in self.options["styles"].items()},
                default=self.options["default_style"],
                source_id=self.options["source"],
            )
        return self._map_styles

    def _request(self, style, bbox, width, height, crs, transparent, format_) -> MapRequest:
        # pygeoapi's get_uri lowercases a CRS URI on its way here.
        if crs is not None and crs.lower() != WEB_MERCATOR.lower():
            raise MapParameterError(user_msg=f"maps are drawn in {WEB_MERCATOR} only")
        # pygeoapi's map route answers f=html with the image itself, as there is no
        # HTML map page: the provider draws a PNG for it too.
        if format_ not in (None, "png", "html"):
            raise MapParameterError(user_msg="maps are drawn as PNG only")
        limit = int(self.options["max_size"])
        if int(width) < 1 or int(height) < 1:
            raise MapParameterError(user_msg="width and height must be at least 1")
        if int(width) > limit or int(height) > limit:
            raise MapTooLargeError(user_msg=f"width and height must be at most {limit}")
        transparent = _flag(transparent)
        try:
            chosen = self._styles().style(style, transparent)
        except KeyError as error:
            raise ProviderItemNotFoundError(user_msg=f"style {style} not found") from error
        except ImportError as error:
            # A source imports the library of its format at its first read, and
            # the library may come from an extra that is not installed.
            raise ProviderGenericError(user_msg=f"map source not available: {error}") from error
        except SourceNotDrawableError as error:
            raise ProviderGenericError(user_msg=f"map source not drawable: {error}") from error
        try:
            xmin, ymin, xmax, ymax = (_clamp(float(value)) for value in bbox)
            if xmin > xmax:
                # The west edge lies east of the east edge: the bbox crosses the
                # antimeridian, and its east edge is one world further on.
                xmax += 2 * HALF_WORLD
            return MapRequest(
                bbox=(xmin, ymin, xmax, ymax),
                width=int(width),
                height=int(height),
                style=chosen,
                transparent=transparent,
            )
        except ValueError as error:
            raise MapParameterError(user_msg=str(error)) from error

    async def _style_request(self, **kwargs: Any) -> MapRequest:
        return await self.run_sync(self._request, **kwargs)

    async def aquery(
        self,
        style: str | None = None,
        bbox: list[float] | None = None,
        width: int = 500,
        height: int = 300,
        crs: str | None = None,
        transparent: Any = True,
        format_: str | None = "png",
        **kwargs: Any,
    ) -> bytes:
        """The PNG of one map; see the module docstring for the limits."""
        request = await self._style_request(
            style=style,
            bbox=bbox if bbox is not None else [-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD],
            width=width,
            height=height,
            crs=crs,
            transparent=transparent,
            format_=format_,
        )
        self._loop = asyncio.get_running_loop()
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(1)
        if self._waiting >= int(self.options["queue"]) + 1:
            raise MapRendererBusyError()
        self._waiting += 1
        try:
            return await self._draw(request)
        finally:
            self._waiting -= 1
            # After close(), the renderer goes as soon as nothing is left to draw:
            # maps queued before the close, or served late by the old sub-app,
            # may have built it again.
            if self._closed and self._waiting == 0 and self._renderer is not None:
                self._discard(self._renderer)

    async def _draw(self, request: MapRequest) -> bytes:
        """The map within ``timeout``, the wait for the renderer included.

        Past the timeout the map answers 504, and its render goes on,
        holding the renderer: cancelling a command would kill the
        renderer's process, and with it the tiles it has cached.
        ``render_limit`` bounds the render.
        """
        loop = asyncio.get_running_loop()
        timeout = float(self.options["timeout"])
        deadline = loop.time() + timeout
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout)
        except TimeoutError:
            raise MapRenderTimeoutError() from None
        drawing = loop.create_task(self._render_then_release(request))
        self._drawing.add(drawing)
        drawing.add_done_callback(self._drawn)
        try:
            return await asyncio.wait_for(asyncio.shield(drawing), max(0.0, deadline - loop.time()))
        except TimeoutError:
            raise MapRenderTimeoutError() from None

    async def _render_then_release(self, request: MapRequest) -> bytes:
        try:
            return await self._render(request)
        finally:
            self._semaphore.release()

    def _drawn(self, drawing: asyncio.Task) -> None:
        self._drawing.discard(drawing)
        # A render that outlived its map fails with nobody awaiting it; its
        # error is already logged, and reading it keeps asyncio quiet.
        if not drawing.cancelled():
            drawing.exception()

    def _render_limit(self) -> float:
        limit = self.options["render_limit"]
        return float(limit) if limit is not None else 4 * float(self.options["timeout"])

    async def _render(self, request: MapRequest) -> bytes:
        if self._renderer is None:
            # In a thread: the first build imports the renderer's modules and looks
            # up its binary on disk.
            self._renderer = await self.run_sync(self._build_renderer)
        renderer = self._renderer
        try:
            return await asyncio.wait_for(renderer.render(request), timeout=self._render_limit())
        except TimeoutError as error:
            self._discard(renderer)
            logger.warning("map render went past render_limit; the renderer is replaced")
            raise MapRenderTimeoutError() from error
        except Exception as error:
            # Any failure counts as a broken renderer. Its message may name
            # the signed archive URL, so only its type reaches the log, and
            # the chain is dropped before the error travels to a client.
            self._discard(renderer)
            logger.warning(f"map renderer failed with {type(error).__name__}; it is replaced")
            raise ProviderGenericError(user_msg="the map renderer failed") from None

    def _build_renderer(self) -> MapRenderer:
        factory = _load_factory(self.options["renderer"])
        try:
            return factory({**self.options, "render_limit": self._render_limit()})
        except ImportError as error:
            raise ProviderGenericError(
                user_msg=f"map rendering is not available: {error}"
            ) from error

    def _discard(self, renderer: MapRenderer) -> None:
        if self._renderer is renderer:
            self._renderer = None
        task = asyncio.get_running_loop().create_task(renderer.aclose())
        # The loop keeps only a weak reference to a task.
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    def query(self, **kwargs: Any) -> bytes:
        """The synchronous face pygeoapi calls.

        The map is drawn on the loop that owns the renderer.
        """
        loop = self._loop
        if loop is None or not loop.is_running():
            raise ProviderGenericError(
                user_msg="maps are drawn on the async route; no event loop owns the renderer"
            )
        return asyncio.run_coroutine_threadsafe(self.aquery(**kwargs), loop).result()

    async def aclose(self) -> None:
        """The async twin of :meth:`close`, which also waits for the renderer to close.

        With maps still drawn or waiting, the last of them closes the renderer,
        as with :meth:`close`.
        """
        self._closed = True
        if self._waiting == 0 and self._renderer is not None:
            self._discard(self._renderer)
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)

    def close(self) -> None:
        """Close the renderer once no map is being drawn or waiting for it.

        Safe to call from any thread: the plugin cache calls it on reload,
        while the old sub-app may still be serving maps with this instance.
        """
        self._closed = True
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        async def close_if_idle() -> None:
            if self._waiting == 0 and self._renderer is not None:
                self._discard(self._renderer)

        asyncio.run_coroutine_threadsafe(close_if_idle(), loop)
