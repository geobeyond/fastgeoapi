"""OGC API Maps drawn with mapli

The provider composes the parts of :mod:`app.provider.maps` with a
:class:`~app.maps.queue.RenderQueue` and MapLibre's styles. Its source
comes from the registry of :mod:`app.maps.sources`, and its default
renderer is MapLibre Native through mapli, which reads the
data itself, through the URL the style carries.
"""

import asyncio
import dataclasses
import hashlib
import importlib.metadata
import json
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
from typing import Any, ClassVar, TYPE_CHECKING

import mapli
from pygeoapi.provider.base import BaseProvider, ProviderGenericError

from app.maps.contract import MapRequest, MapSource, MapStyles
from app.maps.queue import RenderQueue
from app.maps.sources import ObjectUrl, SourceContext
from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from app.provider.maps import (
    MAPS_CONFORMANCE,
    WEB_MERCATOR,
    StyleDocuments,
    build_renderer,
    build_styles,
    check_definition,
    draw_map,
    map_request,
    object_url,
    render_limit,
)
from app.provider.storage.loopback import SOURCES, RangeServer, ensure_range_server

if TYPE_CHECKING:
    from app.maps.contract import MapRequest, MapStyles
    from app.maps.queue import RenderQueue
    from app.provider.maps import SourceFormat
    from app.provider.storage import CachedRanges
    from app.provider.storage.loopback import RangeServer


def style_digest(style: dict[str, Any], source_id: str) -> str:
    """A digest of a style as the renderer gets it, without the address of the collection's data.

    That address names this process's loopback server, with its port and
    token, or a presigned URL. It differs between processes that draw the
    same version of the data, and the map's version already holds the
    data's.
    """
    style = deepcopy(style)
    source = style.get("sources", {}).get(source_id)
    if isinstance(source, dict):
        source.pop("url", None)
        source.pop("tiles", None)
    document = json.dumps(style, sort_keys=True, default=str)
    return hashlib.sha256(document.encode()).hexdigest()[:16]


@dataclasses.dataclass(frozen=True)
class MapliProviderConfig:
    data: str
    max_renderers_per_worker: int
    num_workers: int
    storage_crs: str
    range_cache: bool = True
    data_url: str | None = None
    sign_ttl: int = 3600
    store_options: dict[str, Any] | None = None
    styles: dict[str, Any] = dataclasses.field(default_factory=dict)


class MapliMapProvider(AsyncProviderMixin, StorageBackedMixin, BaseProvider):

    THREAD_SAFE = True
    native_async = True
    conformance_classes: ClassVar[tuple[str, ...]] = MAPS_CONFORMANCE

    cached_ranges: CachedRanges | None  # this is `None` when dealing with local files
    options: MapliProviderConfig
    old_options: dict[str, Any]
    provider_def: dict[str, Any]

    _source_format: "SourceFormat"
    _map_styles: "MapStyles | None"
    _queue: "RenderQueue"
    _range_server: "RangeServer | None"
    _render_pool: mapli.RenderPool

    def __init__(self, provider_def: dict) -> None:
        """Read the options; no I/O happens until the first map."""
        super().__init__(provider_def)
        # CHECK: we may not need self.options at all because all `AsyncProviderMixin`
        # instances self `self.provider_def=provider_def` upon initialization
        self.options = MapliProviderConfig(
            data=provider_def["data"],
            data_url=provider_def.get("data_url"),
            max_renderers_per_worker=provider_def.get("max_renderers_per_worker", 8),
            num_workers=provider_def.get("num_workers", 4),
            range_cache=provider_def.get("range_cache", True),
            sign_ttl=provider_def.get("sign_ttl", 3600),
            storage_crs=provider_def.get("storage_crs", WEB_MERCATOR),
            store_options=provider_def.get("store_options"),
            styles=provider_def.get("styles", {}),
        )
        self.old_options = {
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
            # The name the styles give the collection's source in their `sources`.
            "style_source": "archive",
            # For data in a public bucket: the https address the renderer reads it at.
            "data_url": None,
            "range_cache": True,
            # The elevation encoding of a raster archive: terrarium or mapbox.
            "dem": None,
            "renderer": "app.maps.mapli.create_renderer",
            # The styles go with the renderer: MapLibre styles for MapLibre Native.
            "style_factory": "app.maps.styles.create_maplibre_styles",
            **(provider_def.get("options") or {})
        }
        self._source_format = check_definition(
            provider_def, dataclasses.asdict(self.options)
        )
        self._map_styles = None
        self._range_server = None
        self._render_pool = mapli.RenderPool(
            workers=self.options.num_workers,
            max_renderers_per_worker=self.options.max_renderers_per_worker
        )
        # self._queue = RenderQueue(
        #     lambda: build_renderer(self.options),
        #     size=int(self.options["queue"]),
        #     timeout=float(self.options["timeout"]),
        #     render_limit=render_limit(self.options),
        # )

    def style_names(self) -> list[str]:
        """The configured style names."""
        return sorted(self.options.styles)

    def _object_url(self) -> ObjectUrl:
        cached, server = self.cached_ranges, self._range_server
        if cached is not None and server is not None:
            # The renderer reads the object through this process, by version.
            return ObjectUrl(
                resolver=lambda: server.url_for(cached, cached.known_meta() or cached.meta())
            )
        return object_url(
            self.options.data,
            public_url=self.options.data_url,
            sign=lambda ttl: self.signed_url(ttl),
            ttl=timedelta(seconds=self.options.sign_ttl),
        )

    def _source(self) -> MapSource:
        cached = self.cached_ranges
        context = SourceContext(
            data=self.options.data,
            options=dataclasses.asdict(self.options),
            location=self._object_url,
            ranges=(
                (lambda: cached.at(cached.meta()).read)
                if cached is not None
                else (lambda: self.byte_ranges().read)
            ),
        )
        return self._source_format.build(context)

    def _styles(self) -> MapStyles:
        if self._map_styles is None:
            documents = StyleDocuments(
                self.options["styles"], self.provider_def.get("store_options")
            )
            self._map_styles = build_styles(self._source(), documents, self.options)
        return self._map_styles

    def _request(self, **parameters: Any) -> MapRequest:
        return map_request(
            lambda name, transparent: self._styles().style(name, transparent),
            max_size=int(self.options["max_size"]),
            **parameters,
        )

    def _drawn_version(self, **parameters: Any) -> str:
        request = self._request(**parameters)
        drawn = style_digest(request.style, self.options["style_source"])
        return f"{drawn}|{renderer_version()}"

    async def aversion(
        self,
        style: str | None = None,
        bbox: list[float] | None = None,
        width: int = 500,
        height: int = 300,
        crs: str | None = None,
        transparent: Any = True,
        format_: str | None = "png",
        **kwargs: Any,
    ) -> str | None:
        """The version of the map :meth:`aquery` would draw for these arguments, without drawing it.

        It joins the archive's version, the definition's digest, the digest
        of the style the renderer would get and the renderer's version. The
        request is built as :meth:`aquery` builds it, with the same checks:
        a map that :meth:`aquery` refuses raises the same error here. None
        when the archive's version is unknown.
        """
        data = await self.adata_version()
        if data is None:
            return None
        if self.cached_ranges is not None:
            # The style names the loopback server, which has an address only once started.
            self._range_server = await ensure_range_server()
        # In a thread, as in aquery: the first call reads the style documents and the source.
        drawn = await self.run_sync(
            self._drawn_version,
            style=style,
            bbox=bbox,
            width=width,
            height=height,
            crs=crs,
            transparent=transparent,
            format_=format_,
        )
        return f"{data}|{self.definition_digest()}|{drawn}"

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
        """The PNG of one map.

        :func:`~app.provider.maps.map_request` checks its parameters, and its
        render waits in the :class:`~app.maps.queue.RenderQueue`.
        """
        cached = self.cached_ranges
        if cached is not None:
            self._range_server = await ensure_range_server()
            # Registered only once the version is known: until then, on a reload,
            # the provider this one replaces keeps serving the maps it is drawing.
            # Past the TTL the map draws the version it knows and the HEAD runs behind.
            await cached.ameta_without_waiting()
            SOURCES.register(cached)
        # In a thread: at the first map the styles read their documents and the source.
        request: "MapRequest" = await self.run_sync(
            self._request,
            style=style,
            bbox=bbox,
            width=width,
            height=height,
            crs=crs,
            transparent=transparent,
            format_=format_,
        )
        # return await draw_map(self._queue, request)
        xmin, ymin, xmax, ymax = request.bbox
        return await self._render_pool.arender(
            style_id=request.style,
            lon=xmin + (xmax - xmin) / 2,
            lat=ymin + (ymax - ymin) / 2,
            zoom=None,
            width=request.width,
            height=request.height,
        )

    def query(self, **kwargs: Any) -> bytes:
        """The synchronous face pygeoapi calls.

        The map is drawn on the loop that owns the renderer.
        """
        loop = self._queue.loop
        if loop is None or not loop.is_running():
            raise ProviderGenericError(
                user_msg="maps are drawn on the async route; no event loop owns the renderer"
            )
        return asyncio.run_coroutine_threadsafe(self.aquery(**kwargs), loop).result()

    async def aclose(self) -> None:
        """The async twin of :meth:`close`, which also waits for the renderer to close.

        The loopback server stops serving the data once the renderer is gone.
        """
        await self._queue.aclose()
        self._forget_source()

    def close(self) -> None:
        """Close the renderer once no map is being drawn or waiting for it.

        Safe to call from any thread: the plugin cache calls it on reload,
        while the old sub-app may still be serving maps with this instance.
        The loopback server keeps serving the data to those maps until the
        provider of the new configuration registers it.
        """
        self._queue.close()

    def _forget_source(self) -> None:
        # Only a source that was built can have been registered.
        cached = self.__dict__.get("cached_ranges")
        if cached is not None:
            SOURCES.unregister(cached)
