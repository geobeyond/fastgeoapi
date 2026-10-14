"""OGC API Maps drawn with mapli"""

import asyncio
import dataclasses
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import mapli
from pygeoapi.provider.base import BaseProvider

from app.config.logging import create_logger
from app.maps.sources import (
    ObjectUrl,
    SourceContext,
)
from app.maps.styles import (
    default_raster_style as generate_default_raster_style,
    default_hillshade_style as generate_default_hillshade_style,
    default_style as generate_default_vector_style,
)
from app.provider import maps as provider_maps
from app.provider.base import (
    AsyncProviderMixin,
    StorageBackedMixin,
)

if TYPE_CHECKING:
    from app.maps.contract import (
        MapRequest,
        MapSource,
        MapStyles,
        SourceContent,
    )
    from app.provider.storage import CachedRanges
    from app.provider.storage.loopback import RangeServer

logger = create_logger("app.provider.mapli")


class MapliCollectionStyles:
    """Styles for a mapli map provider.

    Implements the ``app.maps.contract.MapStyles`` protocol.

    This contains a set styles for mapli to apply to the underlying
    collection's map source. The styles are defined in accordance with the
    MapLibre Style Specification.

    Contrary to the ``app.maps.styles.MapLibreStyles`` class, this performs
    eager initialization of default styles.
    """

    _styles: dict[str, str | dict]

    def __init__(
            self,
            collection_map_source: "MapSource",
            **inline_style: dict[str, dict]
    ):
        self._styles = {
            **{k: v for k, v in inline_style.items()}
        }
        source_name = "dataset"  # name used in the default styles to refer to the data source
        if len(self._styles) == 0:  # provide a default style
            content = collection_map_source.content()
            if content.kind == "vector":
                default_style = generate_default_vector_style(
                    vector_layers=content.layers,
                    source=source_name
                )
            elif content.kind == "raster":
                default_style = generate_default_raster_style(
                    source=source_name)
            else:  # "raster-dem":
                default_style = generate_default_hillshade_style(
                    source=source_name)
            default_style["sources"] = {
                source_name: {
                    "type": content.kind,
                    "url": f"pmtiles://{collection_map_source.url()}"
                }
            }
            self._styles["default"] = default_style

    def names(self) -> list[str]:
        """The configured style names."""
        return sorted(self._styles.keys())

    def style(self, name: str | None, transparent: bool) -> Any:
        if name:
            return self._styles[name]
        else:
            return self._styles["default"]


@dataclasses.dataclass(frozen=True)
class MapliMapProviderConfig:
    """Mapli provider config"""

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
    """OGC API Maps provider backed by mapli."""

    THREAD_SAFE = True
    native_async = True
    conformance_classes = provider_maps.MAPS_CONFORMANCE

    # set by StorageBackedMixin
    cached_ranges: "CachedRanges | None"  # this is `None` when dealing with local files

    # set by AsyncProviderMixin
    provider_def: dict[str, Any]

    _config: MapliMapProviderConfig
    _map_styles: "MapStyles"
    _range_server: "RangeServer | None"
    _render_pool: mapli.RenderPool

    def __init__(self, provider_def: dict) -> None:
        super().__init__(provider_def)
        self._config = MapliMapProviderConfig(
            data=provider_def["data"],
            data_url=provider_def.get("options", {}).get("data_url"),
            max_renderers_per_worker=provider_def.get("options", {}).get("max_renderers_per_worker", 8),
            num_workers=provider_def.get("options", {}).get("num_workers", 4),
            range_cache=provider_def.get("range_cache", True),
            sign_ttl=provider_def.get("sign_ttl", 3600),
            storage_crs=provider_def.get("storage_crs", provider_maps.WEB_MERCATOR),
            store_options=provider_def.get("store_options"),
            styles=provider_def.get("styles", {}),
            style_factory=provider_def.get(
                "style_factory", "app.maps.styles.create_maplibre_styles"
            ),
            max_size=provider_def.get("options", {}).get("max_size", 2048),
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
                ),
            )
        )
        self._map_styles = provider_maps.build_styles(
            source=_map_source,
            documents=provider_maps.StyleDocuments(self._config.styles, self._config.store_options),
            options=_config_as_dict,
        )

        self._map_styles = MapliCollectionStyles(_map_source)

        self._render_pool = mapli.RenderPool(
            workers=self._config.num_workers,
            max_renderers_per_worker=self._config.max_renderers_per_worker,
        )
        logger.debug("---------------------------------------------------")
        logger.debug("---------------------------------------------------")
        logger.debug("---------------------------------------------------")
        logger.debug("---------------------------------------------------")
        logger.debug("---------------------------------------------------")
        logger.debug("---------------------------------------------------")
        logger.debug("---------------------------------------------------")
        logger.debug(f"{self._map_styles.names()=}")

        for style_id in self._map_styles.names():
            logger.debug(f"{style_id=}")
            to_register = self._map_styles.style(style_id, transparent=False)
            logger.debug(f"{to_register=}")
            self._render_pool.register_style(
                style_id, json=self._map_styles.style(style_id, transparent=False)
            )

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
        logger.debug(f"{locals()=}")
        """Generate a map image."""
        map_request = provider_maps.map_request(
            style_for=(
                lambda name, is_transparent: self._map_styles.style(name, is_transparent)
            ),
            max_size=self._config.max_size,
            style=style,
            bbox=bbox,
            width=width,
            height=height,
            crs=crs,
            transparent=transparent,
            format_=format_,
        )
        logger.debug(f"{map_request.style=}")
        logger.debug(f"{bbox=}")
        logger.debug(f"{map_request.bbox=}")
        logger.debug(f"{map_request.width=}")
        logger.debug(f"{map_request.height=}")
        style_id = style or "default"
        logger.debug(f"{style_id=}")
        if self._render_pool.has_style(style_id):
            return await self._render_pool.arender_from_bounds(
                style_id=style_id,
                #bbox=map_request.bbox,
                bbox=(11.4, 41.2, 14.1, 42.9),
                width=map_request.width,
                height=map_request.height,
            )
        else:
            raise RuntimeError(f"unknown style: {style}")

    def query(self, **kwargs: Any) -> bytes:
        """Generate a map image."""
        return asyncio.run(self.aquery(), **kwargs)
