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
from app.maps.styles import MapLibreStyles
from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from app.provider.maps import (
    MAPS_CONFORMANCE,
    build_renderer,
    check_definition,
    draw_map,
    map_request,
    object_url,
    read_style,
    render_limit,
)

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
    "renderer": "app.maps.mlnative.create_renderer",
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
        return object_url(
            self.provider_def["data"],
            public_url=self.options["data_url"],
            sign=lambda ttl: self.signed_url(ttl),
            ttl=timedelta(seconds=self.options["sign_ttl"]),
        )

    def _source(self) -> MapSource:
        context = SourceContext(
            data=self.provider_def["data"],
            options=self.options,
            location=self._object_url,
            ranges=lambda: self.byte_ranges().read,
        )
        return self._source_format.build(context)

    def _styles(self) -> MapStyles:
        if self._map_styles is None:
            store_options = self.provider_def.get("store_options")
            documents = {
                name: read_style(where, store_options)
                for name, where in self.options["styles"].items()
            }
            self._map_styles = MapLibreStyles(
                self._source(),
                documents,
                default=self.options["default_style"],
                source_id=self.options["style_source"],
            )
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
        """The async twin of :meth:`close`, which also waits for the renderer to close."""
        await self._queue.aclose()

    def close(self) -> None:
        """Close the renderer once no map is being drawn or waiting for it.

        Safe to call from any thread: the plugin cache calls it on reload,
        while the old sub-app may still be serving maps with this instance.
        """
        self._queue.close()
