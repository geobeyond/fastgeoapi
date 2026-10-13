"""OGC API Maps drawn with mapli"""

import asyncio
import dataclasses
from datetime import timedelta
from typing import Any, TYPE_CHECKING

import mapli
from pygeoapi.provider.base import BaseProvider

from app.maps.sources import (
    ObjectUrl,
    SourceContext,
)
from app.provider.base import (
    AsyncProviderMixin,
    StorageBackedMixin,
)
from app.provider import maps as provider_maps

if TYPE_CHECKING:
    from app.maps.contract import (
        MapRequest,
        MapStyles,
    )
    from app.provider.storage import CachedRanges
    from app.provider.storage.loopback import RangeServer


@dataclasses.dataclass(frozen=True)
class MapliProviderConfig:
    data: str
    max_renderers_per_worker: int
    num_workers: int
    storage_crs: str
    max_size: int = 2048
    range_cache: bool = True
    data_url: str | None = None
    sign_ttl: int = 3600
    store_options: dict[str, Any] | None = None
    styles: dict[str, Any] = dataclasses.field(default_factory=dict)
    style_factory: str = "app.maps.styles.create_maplibre_styles"


class MapliMapProvider(AsyncProviderMixin, StorageBackedMixin, BaseProvider):

    THREAD_SAFE = True
    native_async = True
    conformance_classes = provider_maps.MAPS_CONFORMANCE

    # set by StorageBackedMixin
    cached_ranges: "CachedRanges | None"  # this is `None` when dealing with local files

    # set by AsyncProviderMixin
    provider_def: dict[str, Any]

    _config: MapliProviderConfig
    _map_styles: "MapStyles"
    _range_server: "RangeServer | None"
    _render_pool: mapli.RenderPool

    def __init__(self, provider_def: dict) -> None:
        super().__init__(provider_def)
        self._config = MapliProviderConfig(
            data=provider_def["data"],
            data_url=provider_def.get("data_url"),
            max_renderers_per_worker=provider_def.get("max_renderers_per_worker", 8),
            num_workers=provider_def.get("num_workers", 4),
            range_cache=provider_def.get("range_cache", True),
            sign_ttl=provider_def.get("sign_ttl", 3600),
            storage_crs=provider_def.get("storage_crs", provider_maps.WEB_MERCATOR),
            store_options=provider_def.get("store_options"),
            styles=provider_def.get("styles", {}),
            style_factory=provider_def.get(
                "style_factory", "app.maps.styles.create_maplibre_styles"),
            max_size=provider_def.get("max_size", 2048)
        )
        self._range_server = None
        _config_as_dict = dataclasses.asdict(self._config)
        _source_format = provider_maps.check_definition(provider_def, _config_as_dict)
        _map_source = _source_format.build(
            SourceContext(
                data=self._config.data,
                options=_config_as_dict,
                location=self._get_object_url,
                ranges=(
                    (lambda: self.cached_ranges.at(self.cached_ranges.meta()).read)
                    if self.cached_ranges is not None
                    else (lambda: self.byte_ranges().read)
                )
            )
        )
        self._map_styles = provider_maps.build_styles(
            source=_map_source,
            documents=provider_maps.StyleDocuments(
                self._config.styles, self._config.store_options
            ),
            options=_config_as_dict
        )
        self._render_pool = mapli.RenderPool(
            workers=self._config.num_workers,
            max_renderers_per_worker=self._config.max_renderers_per_worker
        )

    def style_names(self) -> list[str]:
        """The configured style names."""
        return sorted(self._map_styles.names())

    def _get_object_url(self) -> ObjectUrl:
        cached, server = self.cached_ranges, self._range_server
        if cached is not None and server is not None:
            # The renderer reads the object through this process, by version.
            return ObjectUrl(
                resolver=lambda: server.url_for(cached, cached.known_meta() or cached.meta())
            )
        return provider_maps.object_url(
            self._config.data,
            public_url=self._config.data_url,
            sign=lambda ttl: self.signed_url(ttl),
            ttl=timedelta(seconds=self._config.sign_ttl),
        )

    def _generate_map_request(self, **parameters: Any) -> "MapRequest":
        return provider_maps.map_request(
            style_for=(
                lambda name, transparent: self._map_styles.style(
                    name, transparent)
            ),
            max_size=self._config.max_size,
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
        """Generate a map image."""
        map_request = provider_maps.map_request(
            style_for=(
                lambda name, is_transparent: self._map_styles.style(
                    name, is_transparent)
            ),
            max_size=self._config.max_size,
            style=style,
            bbox=bbox,
            width=width,
            height=height,
            crs=crs,
            transparent=transparent,
            format_=format_
        )
        return await self._render_pool.arender_from_bounds(
            style_id=map_request.style,
            bbox=map_request.bbox,
            width=map_request.width,
            height=map_request.height,
        )

    def query(self, **kwargs: Any) -> bytes:
        return asyncio.run(self.aquery(), **kwargs)

    async def aclose(self) -> None:
        pass

    def close(self) -> None:
        pass
