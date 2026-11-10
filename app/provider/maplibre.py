"""OGC API Maps drawn with MapLibre: MapLibre styles, MapLibre Native.

The provider composes the parts of :mod:`app.provider.maps` with a
:class:`~app.maps.queue.RenderQueue` and MapLibre's styles. Its source
comes from the registry of :mod:`app.maps.sources`, and its default
renderer is MapLibre Native through the mlnative fork, which reads the
data itself, through the URL the style carries.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
from copy import deepcopy
from datetime import timedelta
from functools import lru_cache
from typing import Any

from pygeoapi.provider.base import BaseProvider, ProviderGenericError

from app.interfaces.providers import (
    MapCapabilities,
    MapFormat,
    MapLimits,
    MapParameters,
)
from app.maps.contract import MapRequest, MapSource, MapStyles
from app.maps.queue import RenderQueue
from app.maps.sources import ObjectUrl, SourceContext
from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from app.provider.maps import (
    WEB_MERCATOR,
    StyleDocuments,
    build_map_request,
    build_object_url,
    build_renderer,
    build_styles,
    check_definition,
    draw_map,
    render_limit,
)
from app.provider.storage.loopback import (
    SOURCES,
    RangeServer,
    ensure_range_server,
)


@lru_cache(maxsize=1)
def get_renderer_version() -> str:
    """The version of the installed mlnative, or ``none`` without it."""
    try:
        return importlib.metadata.version("mlnative")
    except importlib.metadata.PackageNotFoundError:
        return "none"


def digest_style(style: dict[str, Any], source_id: str) -> str:
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
    # The name the styles give the collection's source in their `sources`.
    "style_source": "archive",
    # For data in a public bucket: the https address the renderer reads it at.
    "data_url": None,
    "range_cache": True,
    # The elevation encoding of a raster archive: terrarium or mapbox.
    "dem": None,
    "renderer": "app.maps.mlnative.create_renderer",
    # The styles go with the renderer: MapLibre styles for MapLibre Native.
    "style_factory": "app.maps.styles.create_maplibre_styles",
}


class MapLibreMapProvider(AsyncProviderMixin, StorageBackedMixin, BaseProvider):
    """A map provider drawn with MapLibre styles by MapLibre Native."""

    THREAD_SAFE = True
    native_async = True

    def __init__(self, provider_def: dict) -> None:
        """Read the options; no I/O happens until the first map."""
        super().__init__(provider_def)
        self.options = {**DEFAULTS, **(provider_def.get("options") or {})}
        self._source_format = check_definition(provider_def, self.options)
        self._map_styles: MapStyles | None = None
        self._range_server: RangeServer | None = None
        self._queue = RenderQueue(
            lambda: build_renderer(self.options),
            size=int(self.options["queue"]),
            timeout=float(self.options["timeout"]),
            render_limit=render_limit(self.options),
        )

    @property
    def limits(self) -> MapLimits:
        """The limits of the drawn maps: ``max_size`` on both sides, no limit on the area."""
        size = int(self.options["max_size"])
        return MapLimits(
            max_width=size,
            max_height=size,
            max_pixels=None,
        )

    @property
    def capabilities(self) -> MapCapabilities:
        """Web Mercator and PNG as the CRS and the encoding of the drawn maps."""
        return MapCapabilities(crs=(WEB_MERCATOR,), formats=(MapFormat.PNG,))

    @property
    def renderer_is_built(self) -> bool:
        """Whether a renderer is currently alive."""
        return self._queue.renderer_is_built

    @property
    def waiting(self) -> int:
        """How many maps are being drawn or are waiting for the renderer."""
        return self._queue.waiting

    def list_style_names(self) -> list[str]:
        """The configured style names."""
        return sorted(self.options["styles"])

    def _locate_object(self) -> ObjectUrl:
        cached, server = self.cached_ranges, self._range_server
        if cached is not None and server is not None:
            # The renderer reads the object through this process, by version.
            return ObjectUrl(
                resolver=lambda: server.url_for(
                    cached, cached.known_meta() or cached.meta()
                )
            )
        return build_object_url(
            self.provider_def["data"],
            public_url=self.options["data_url"],
            sign=lambda ttl: self.signed_url(ttl),
            ttl=timedelta(seconds=self.options["sign_ttl"]),
        )

    def _build_source(self) -> MapSource:
        cached = self.cached_ranges
        context = SourceContext(
            data=self.provider_def["data"],
            options=self.options,
            location=self._locate_object,
            ranges=(
                (lambda: cached.at(cached.meta()).read)
                if cached is not None
                else (lambda: self.byte_ranges().read)
            ),
        )
        return self._source_format.build(context)

    def _load_styles(self) -> MapStyles:
        if self._map_styles is None:
            documents = StyleDocuments(
                self.options["styles"], self.provider_def.get("store_options")
            )
            self._map_styles = build_styles(
                self._build_source(), documents, self.options
            )
        return self._map_styles

    def _build_request(self, parameters: MapParameters) -> MapRequest:
        return build_map_request(
            lambda name, transparent: self._load_styles().style(
                name, transparent
            ),
            max_size=int(self.options["max_size"]),
            style=parameters.style,
            bbox=parameters.bbox,
            width=parameters.width,
            height=parameters.height,
            crs=parameters.crs,
            transparent=parameters.transparent,
            format_=parameters.format_,
        )

    def _compute_drawn_version(self, parameters: MapParameters) -> str:
        request = self._build_request(parameters)
        drawn = digest_style(request.style, self.options["style_source"])
        return f"{drawn}|{get_renderer_version()}"

    async def aget_version(self, parameters: MapParameters) -> str | None:
        """Get the version of the drawn map, without drawing it.

        It joins the archive's version, the definition's digest, the digest
        of the style the renderer would get and the renderer's version. The
        request is built as :meth:`arender_map` builds it, so a map that
        :meth:`arender_map` refuses raises the same error here.

        Parameters
        ----------
        parameters
            The checked parameters of the map.

        Returns
        -------
        str or None
            The version, or None when the archive's version is unknown.
        """
        data = await self.adata_version()
        if data is None:
            return None
        if self.cached_ranges is not None:
            # The style names the loopback server, which has an address only once started.
            self._range_server = await ensure_range_server()
        # In a thread, as in arender_map: the first call reads the style documents and the source.
        drawn = await self.run_sync(self._compute_drawn_version, parameters)
        return f"{data}|{self.definition_digest()}|{drawn}"

    async def arender_map(self, parameters: MapParameters) -> bytes:
        """Draw the map and return the PNG.

        :func:`~app.provider.maps.build_map_request` checks its parameters, and its
        render waits in the :class:`~app.maps.queue.RenderQueue`. An archive
        has no time and no other dimension, so ``datetime_`` and ``subsets``
        change nothing.

        Parameters
        ----------
        parameters
            The checked parameters of the map.

        Returns
        -------
        bytes
            The PNG.
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
        request = await self.run_sync(self._build_request, parameters)
        return await draw_map(self._queue, request)

    def query(self, **kwargs: Any) -> bytes:
        """Draw the map for pygeoapi's synchronous route.

        The map is drawn on the event loop that owns the renderer. Outside
        fastgeoapi no loop owns it, and the call fails.
        """
        loop = self._queue.loop
        if loop is None or not loop.is_running():
            raise ProviderGenericError(
                user_msg="maps are drawn on the async route; no event loop owns the renderer"
            )
        parameters = read_pygeoapi_arguments(kwargs)
        return asyncio.run_coroutine_threadsafe(
            self.arender_map(parameters), loop
        ).result()

    async def aclose(self) -> None:
        """Close the renderer and wait until it is closed.

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


def read_pygeoapi_arguments(arguments: dict[str, Any]) -> MapParameters:
    """Read the keyword arguments pygeoapi passes to ``query`` as map parameters.

    pygeoapi also passes ``bbox-crs``, once the bbox is already in ``crs``,
    and ``select_properties``; neither changes the map. A missing value
    takes the default of a map pygeoapi asks for without it.

    Parameters
    ----------
    arguments
        The keyword arguments of ``query``.

    Returns
    -------
    MapParameters
        The parameters ``arender_map`` takes.
    """
    bbox = arguments.get("bbox")
    return MapParameters(
        style=arguments.get("style"),
        bbox=tuple(bbox) if bbox is not None else None,
        width=arguments.get("width", 500),
        height=arguments.get("height", 300),
        crs=arguments.get("crs"),
        transparent=arguments.get("transparent", True),
        format_=arguments.get("format_", "png"),
        datetime_=arguments.get("datetime_"),
        subsets=arguments.get("subsets"),
    )
