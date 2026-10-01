"""OGC API Maps drawn with MapLibre: MapLibre styles, MapLibre Native.

The provider composes the parts of :mod:`app.provider.maps` with a
:class:`~app.maps.queue.RenderQueue` and MapLibre's styles. Its source
comes from the registry of :mod:`app.maps.sources`, and its default
renderer is MapLibre Native through the mlnative fork, which reads the
data itself, through the URL the style carries.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, ClassVar

from pygeoapi.provider.base import BaseProvider, ProviderGenericError

from app.maps.contract import MapRequest, MapSource, MapStyles
from app.maps.queue import RenderQueue
from app.maps.sources import ObjectUrl, SourceContext
from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from app.provider.maps import (
    MAPS_CONFORMANCE,
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
    conformance_classes: ClassVar[tuple[str, ...]] = MAPS_CONFORMANCE

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
    def renderer_is_built(self) -> bool:
        """Whether a renderer is currently alive."""
        return self._queue.renderer_is_built

    @property
    def waiting(self) -> int:
        """How many maps are being drawn or are waiting for the renderer."""
        return self._queue.waiting

    def style_names(self) -> list[str]:
        """The configured style names."""
        return sorted(self.options["styles"])

    def _object_url(self) -> ObjectUrl:
        cached, server = self.cached_ranges, self._range_server
        if cached is not None and server is not None:
            # The renderer reads the object through this process, by version.
            return ObjectUrl(
                resolver=lambda: server.url_for(cached, cached.known_meta() or cached.meta())
            )
        return object_url(
            self.provider_def["data"],
            public_url=self.options["data_url"],
            sign=lambda ttl: self.signed_url(ttl),
            ttl=timedelta(seconds=self.options["sign_ttl"]),
        )

    def _source(self) -> MapSource:
        cached = self.cached_ranges
        context = SourceContext(
            data=self.provider_def["data"],
            options=self.options,
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
        request = await self.run_sync(
            self._request,
            style=style,
            bbox=bbox,
            width=width,
            height=height,
            crs=crs,
            transparent=transparent,
            format_=format_,
        )
        return await draw_map(self._queue, request)

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
