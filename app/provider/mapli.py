"""OGC API Maps drawn with mapli"""

import asyncio
import dataclasses
import math
from datetime import timedelta
from typing import (
    Any,
    Sequence,
    TYPE_CHECKING,
)

import mapli
from pygeoapi.provider.base import BaseProvider
from pygeoapi.crs import transform_bbox

from app.config.logging import create_logger
from app.maps.sources import (
    ObjectUrl,
    SourceContext,
)
from app.provider import maps as provider_maps
from app.provider.base import (
    AsyncProviderMixin,
    StorageBackedMixin,
)

if TYPE_CHECKING:
    from app.maps.contract import MapSource
    from app.provider.storage import CachedRanges
    from app.provider.storage.loopback import RangeServer

logger = create_logger("app.provider.mapli")

WEB_MERCATOR_HALF_WIDTH = 20_037_508.342789244
CRS_84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


@dataclasses.dataclass(frozen=True)
class MapliMapProviderConfig:
    """Mapli provider config"""

    data: str
    max_renderers_per_worker: int
    num_workers: int
    storage_crs: str
    default_vector_colors: tuple[str, ...] = (
        "#e15759",
        "#4e79a7",
        "#59a14f",
        "#f28e2b",
        "#76b7b2",
        "#b07aa1",
    )
    default_background_color: str = "#ffffff"
    default_hillshade_background_color: str = "#f2efe9"
    min_image_width: int = 10
    max_image_width: int = 2048
    min_image_height: int = 10
    max_image_height: int = 2048
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
    _range_server: "RangeServer | None"
    _render_pool: mapli.RenderPool

    _map_styles: dict[str, str | dict]

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
            default_background_color=provider_def.get("default_background_color", "#ffffff"),
            min_image_width=(
                provider_def
                .get("options", {})
                .get("min_image_width", 10)
            ),
            max_image_width=(
                provider_def
                .get("options", {})
                .get(
                    "max_image_width",
                    provider_def.get("options", {}).get("max_size", 2048)
                )
            ),
            min_image_height=(
                provider_def
                .get("options", {})
                .get("min_image_height", 10)
            ),
            max_image_height=(
                provider_def
                .get("options", {})
                .get(
                    "max_image_height",
                    provider_def.get("options", {}).get("max_size", 2048)
                )
            ),
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
        self._map_styles = self._initialize_map_styles(_map_source)
        self._render_pool = mapli.RenderPool(
            workers=self._config.num_workers,
            max_renderers_per_worker=self._config.max_renderers_per_worker,
        )

    def _get_object_url(self) -> ObjectUrl:
        cached, server = self.cached_ranges, self._range_server
        if cached is not None and server is not None:
            return ObjectUrl(
                resolver=lambda: server.url_for(cached, cached.known_meta() or cached.meta())
            )
        return provider_maps.object_url(
            self._config.data,
            public_url=self._config.data_url,
            sign=lambda ttl: self.signed_url(ttl),
            ttl=timedelta(seconds=self._config.sign_ttl),
        )

    def _initialize_map_styles(
            self,
            collection_map_source: "MapSource",
            **custom_style: dict[str, dict | str],
    ) -> dict[str, str | dict]:
        map_styles = {**{k: v for k, v in custom_style.items()}}
        default_source_name = "dataset"  # name used in default styles to refer to the data source
        if len(map_styles) == 0:  # generate default style
            content = collection_map_source.content()
            if content.kind == "vector":
                default_style = generate_default_vector_style(
                    vector_layers=content.layers,
                    source=default_source_name,
                    colors=self._config.default_vector_colors,
                    background_color=self._config.default_background_color,
                )
            elif content.kind == "raster":
                default_style = generate_default_raster_style(
                    source=default_source_name,
                    background_color=self._config.default_background_color,
                )
            else:  # "raster-dem":
                default_style = generate_default_hillshade_style(
                    source=default_source_name,
                    background_color=self._config.default_hillshade_background_color
                )
            url_prefix = "pmtiles://" if collection_map_source.format == "pmtiles" else ""
            default_style["sources"] = {
                default_source_name: {
                    "type": content.kind,
                    "url": f"{url_prefix}{collection_map_source.url()}"
                }
            }
            map_styles["default"] = default_style
        return map_styles

    def _generate_style(
            self,
            style_identifier: str,
            transparent_background: bool
    ) -> dict | str:
        try:
            style_definition = self._map_styles[style_identifier]
        except KeyError:
            raise provider_maps.MapParameterError(user_msg="Unknown style {}".format(style_identifier))
        if isinstance(style_definition, str):
            # this is a URL to a remote style - TODO: retrieve the style from the remote and modify if needed
            return style_definition
        else:
            result = style_definition.copy()
            for background_layer in [
                layer
                for layer in result.get("layers", [])
                if layer.get("type") == "background"
            ]:
                layout_definition = background_layer.setdefault("layout", {})
                layout_definition["visibility"] = "none" if transparent_background else "visible"
            return result

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
        if format_ not in ("png", "html"):
            raise provider_maps.MapParameterError(user_msg="maps are drawn as PNG only")

        if not self._config.min_image_width <= width <= self._config.max_image_width:
            raise provider_maps.MapParameterError(
                user_msg="Please provide a width between {} and {}".format(
                    self._config.min_image_width, self._config.max_image_width)
            )

        if not self._config.min_image_height <= height <= self._config.max_image_height:
            raise provider_maps.MapParameterError(
                user_msg="Please provide a height between {} and {}".format(
                    self._config.min_image_height, self._config.max_image_height)
            )
        effective_crs = crs or provider_maps.WEB_MERCATOR
        if effective_crs.lower() != provider_maps.WEB_MERCATOR.lower():
            raise provider_maps.MapParameterError(
                user_msg=f"maps are drawn in {provider_maps.WEB_MERCATOR} only")

        # pygeoapi (and fastgeoapi) don't parse the `transparent` query param:
        # https://github.com/geopython/pygeoapi/issues/2444
        if isinstance(transparent, str):
            with_transparency = True if transparent.lower() == "true" else False
        else:
            with_transparency = transparent

        web_mercator_bbox = (
            [float(i) for i in bbox]
            if bbox
            else (
                -WEB_MERCATOR_HALF_WIDTH, -WEB_MERCATOR_HALF_WIDTH,
                WEB_MERCATOR_HALF_WIDTH, WEB_MERCATOR_HALF_WIDTH
            )
        )
        lon_lat_bbox = parse_web_mercator_bbox_as_crs84_bbox(web_mercator_bbox)

        style_id = style or "default"
        registered_style_identifier = "-".join((style_id, "transparent" if transparent else ""))
        if not self._render_pool.has_style(registered_style_identifier):
            style_definition = self._generate_style(style_id, transparent_background=with_transparency)
            if isinstance(style_definition, str):
                self._render_pool.register_style(registered_style_identifier, url=style_definition)
            else:
                self._render_pool.register_style(registered_style_identifier, json=style_definition)
        return await self._render_pool.arender_from_bounds(
            style_id=registered_style_identifier,
            bbox=lon_lat_bbox,
            width=width,
            height=height,
        )

    def query(self, **kwargs: Any) -> bytes:
        """Generate a map image."""
        return asyncio.run(self.aquery(), **kwargs)


def parse_web_mercator_bbox_as_crs84_bbox(
    web_mercator_bbox: Sequence[float],
) -> tuple[float, float, float, float]:
    """Parse a web mercator bbox into a crs84 bbox suitable for feeding into mapli."""
    xmin, ymin, xmax, ymax = (
        clamp_value(i, -WEB_MERCATOR_HALF_WIDTH, WEB_MERCATOR_HALF_WIDTH)
        for i in web_mercator_bbox
    )
    if xmin > xmax:
        # The west edge lies east of the east edge: the bbox crosses the
        # antimeridian, and its east edge is one world further on.
        xmax += 2 * WEB_MERCATOR_HALF_WIDTH

    return tuple(
        transform_bbox(
            [xmin, ymin, xmax, ymax],
            from_crs=provider_maps.WEB_MERCATOR,
            to_crs=CRS_84,
            always_xy=True
        )
    )


def clamp_value(
        value: float,
        lower_bound: float,
        upper_bound: float
) -> float:
    if math.isnan(value):
        return value
    return max(lower_bound, min(upper_bound, value))


def generate_default_vector_style(
        vector_layers: Sequence[str],
        source: str,
        colors: Sequence[str],
        background_color: str = "#ffffff"
) -> dict[str, Any]:
    layers: list[dict[str, Any]] = [
        {"id": "background", "type": "background", "paint": {"background-color": background_color}}
    ]
    for index, name in enumerate(vector_layers):
        colour = colors[index % len(colors)]
        common = {"source": source, "source-layer": name}
        layers += [
            {
                "id": f"{name}-fill",
                "type": "fill",
                **common,
                "filter": ["==", ["geometry-type"], "Polygon"],
                "paint": {"fill-color": colour, "fill-opacity": 0.3},
            },
            {
                "id": f"{name}-line",
                "type": "line",
                **common,
                "paint": {"line-color": colour, "line-width": 1},
            },
            {
                "id": f"{name}-circle",
                "type": "circle",
                **common,
                "filter": ["==", ["geometry-type"], "Point"],
                "paint": {"circle-color": colour, "circle-radius": 3},
            },
        ]
    return {"version": 8, "sources": {}, "layers": layers}


def generate_default_raster_style(
        source: str,
        background_color: str = "#ffffff"
) -> dict[str, Any]:
    return {
        "version": 8,
        "sources": {},
        "layers": [
            {"id": "background", "type": "background", "paint": {"background-color": background_color}},
            {"id": "raster", "type": "raster", "source": source},
        ],
    }


def generate_default_hillshade_style(
        source: str,
        background_color: str = "#f2efe9",
        shadow_color: str = "#473b24",
        highlight_color: str = "#ffffff",
        accent_color: str = "#6b5b45"
) -> dict[str, Any]:
    """A plain MapLibre style that shades the relief of the elevation ``source``."""
    return {
        "version": 8,
        "sources": {},
        "layers": [
            {"id": "background", "type": "background", "paint": {"background-color": background_color}},
            {
                "id": "hillshade",
                "type": "hillshade",
                "source": source,
                "paint": {
                    "hillshade-exaggeration": 0.6,
                    "hillshade-shadow-color": shadow_color,
                    "hillshade-highlight-color": highlight_color,
                    "hillshade-accent-color": accent_color,
                },
            },
        ],
    }
