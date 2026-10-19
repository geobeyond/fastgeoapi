"""Fastgeoapi provider for OGC API Maps that uses mapli for rendering."""

import asyncio
import dataclasses
import math
from collections.abc import Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
)

import mapli
from pygeoapi.crs import transform_bbox
from pygeoapi.provider.base import (
    BaseProvider,
    ProviderGenericError,
)

from app.config.logging import create_logger
from app.maps.sources import (
    ObjectUrl,
    SourceContent,
    SourceContext,
    source_for,
)
from app.provider.base import (
    AsyncProviderMixin,
    StorageBackedMixin,
)
from app.provider.maps import (
    HALF_WORLD,
    MAPS_CONFORMANCE,
    WEB_MERCATOR,
    MapParameterError,
    is_bucket,
)
from app.provider.storage.cache import range_cache_enabled
from app.provider.storage.loopback import SOURCES, ensure_range_server

if TYPE_CHECKING:
    from app.provider.storage import CachedRanges
    from app.provider.storage.loopback import RangeServer

logger = create_logger("app.provider.mapli")

CRS_84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


@dataclasses.dataclass(frozen=True)
class MapliMapProviderConfig:
    """Configuration for mapli provider."""

    _supported_dem_encodings: ClassVar[list[str]] = ["mapbox", "terrarium"]

    data: str
    num_workers: int = 4
    max_renderers_per_worker: int = 8
    storage_crs: str = WEB_MERCATOR
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
    default_style: str | None = None
    dem_data_encodings: str | None = None
    min_image_width: int = 10
    max_image_width: int = 2048
    min_image_height: int = 10
    max_image_height: int = 2048
    data_url: str | None = None
    store_options: dict[str, Any] | None = None
    styles: dict[str, Any] = dataclasses.field(default_factory=dict)

    def __post_init__(self):
        """Perform further validation of input parameters"""
        if self.storage_crs != WEB_MERCATOR:
            raise ProviderGenericError(
                user_msg=(f"MapliMapProvider only supports {WEB_MERCATOR!r} as its storage_crs"),
            )
        if self.default_style and self.default_style not in self.styles.keys():
            raise ProviderGenericError(
                user_msg=(
                    f"default_style {self.default_style!r} is not among the configured styles"
                )
            )
        if self.dem_data_encodings and self.dem_data_encodings not in ("mapbox", "terrarium"):
            raise ProviderGenericError(
                user_msg=(
                    f"dem must be one of {self._supported_dem_encodings!r}, "
                    f"not {self.dem_data_encodings!r}"
                )
            )

    @classmethod
    def from_pygeoapi_provider_def(cls, provider_def: dict) -> "MapliMapProviderConfig":
        """Generate an instance from a pygeoapi provider definition dictionary."""
        return cls(
            data=provider_def["data"],
            data_url=provider_def.get("options", {}).get("data_url"),
            max_renderers_per_worker=provider_def.get("options", {}).get(
                "max_renderers_per_worker", 8
            ),
            num_workers=provider_def.get("options", {}).get("num_workers", 4),
            storage_crs=provider_def.get("storage_crs", WEB_MERCATOR),
            store_options=provider_def.get("store_options"),
            styles=provider_def.get("styles", {}),
            default_background_color=provider_def.get("default_background_color", "#ffffff"),
            min_image_width=(provider_def.get("options", {}).get("min_image_width", 10)),
            max_image_width=(
                provider_def.get("options", {}).get(
                    "max_image_width", provider_def.get("options", {}).get("max_size", 2048)
                )
            ),
            min_image_height=(provider_def.get("options", {}).get("min_image_height", 10)),
            max_image_height=(
                provider_def.get("options", {}).get(
                    "max_image_height", provider_def.get("options", {}).get("max_size", 2048)
                )
            ),
        )


class MapliMapProvider(AsyncProviderMixin, StorageBackedMixin, BaseProvider):
    """OGC API Maps provider backed by mapli."""

    # Needed by fastgeoapi's plugin loading mechanism
    THREAD_SAFE = True

    # Needed by AsyncProviderMixin
    native_async = True

    # Needed by pygeoapi's conformance machinery
    conformance_classes = MAPS_CONFORMANCE

    # Automatically set by AsyncProviderMixin
    provider_def: dict[str, Any]

    # Automatically set by StorageBackedMixin
    # NOTE: This property having a value is what unlocks being able to
    # use fastgeoapi's builtin local http cache server. It will be non-None
    # if this provider's configured `data` points to a remote resource and if
    # the provider's configured `options.range_cache` is not set to False
    cached_ranges: "CachedRanges | None"

    _DEFAULT_STYLE_NAME = "default"

    # Configuration explicitly used by this provider
    _config: MapliMapProviderConfig

    # The fastgeoapi local http cache server which may be used as a local http cache
    _range_server: "RangeServer | None"

    _render_pool: mapli.RenderPool
    _map_styles: dict[str, str | dict]

    def __init__(self, provider_def: dict) -> None:
        super().__init__(provider_def)
        self._range_server = None
        self._config = MapliMapProviderConfig.from_pygeoapi_provider_def(provider_def)
        if self._config.data_url is None:
            data_comes_from_bucket = (
                "://" in self._config.data
                and not self._config.data.startswith(("file://", "http://", "https://"))
            )
            should_use_local_cache = (
                provider_def.get("options", {}).get("range_cache", True) and range_cache_enabled()
            )
            if data_comes_from_bucket and not should_use_local_cache:
                raise ProviderGenericError(
                    user_msg=("a public bucket needs options.data_url, the https URL of the data")
                )

        try:
            _source_format = source_for(self._config.data)
        except LookupError as error:
            raise ProviderGenericError(user_msg=f"map source not supported: {error}") from error

        # Cannot create default styles and register them with mapli yet, because
        # fastgeoapi's local cache initialization is async
        self._map_styles = {}
        self._render_pool = mapli.RenderPool(
            workers=self._config.num_workers,
            max_renderers_per_worker=self._config.max_renderers_per_worker,
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
        if format_ not in ("png", "html"):
            raise MapParameterError(user_msg="maps are drawn as PNG only")

        # fastgeoapi's async maps route does not parse the `transparent` query param:
        # https://github.com/geobeyond/fastgeoapi/issues/491
        if isinstance(transparent, str):
            with_transparency = True if transparent.lower() == "true" else False
        else:
            with_transparency = transparent

        if not self._config.min_image_width <= width <= self._config.max_image_width:
            raise MapParameterError(
                user_msg=(
                    f"Please provide a width between {self._config.min_image_width} "
                    f"and {self._config.max_image_width}"
                )
            )

        if not self._config.min_image_height <= height <= self._config.max_image_height:
            raise MapParameterError(
                user_msg=(
                    f"Please provide a height between {self._config.min_image_height} "
                    f"and {self._config.max_image_height}"
                )
            )
        effective_crs = crs or WEB_MERCATOR
        if effective_crs.lower() != WEB_MERCATOR.lower():
            raise MapParameterError(user_msg=f"maps are drawn in {WEB_MERCATOR} only")

        web_mercator_bbox = (
            [float(i) for i in bbox] if bbox else (-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD)
        )
        if any(math.isnan(i) for i in web_mercator_bbox):
            raise ProviderGenericError("bounding box contains NaN values")
        lon_lat_bbox = parse_web_mercator_bbox_as_crs84_bbox(web_mercator_bbox)

        if len(self._map_styles) == 0:  # this is the first time we are running
            await self._initialize_styles()

        style_id = style or self._DEFAULT_STYLE_NAME
        registered_style_identifier = "-".join(
            (style_id, "transparent" if with_transparency else "")
        )
        if not self._render_pool.has_style(registered_style_identifier):
            style_definition = self._generate_style(
                style_id, transparent_background=with_transparency
            )
            logger.debug(f"{style_definition=}")
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

    async def _initialize_styles(self) -> None:
        if self.cached_ranges:
            self._range_server = await ensure_range_server()
            SOURCES.register(self.cached_ranges)
        try:
            _source_format = source_for(self._config.data)
        except LookupError as error:
            raise ProviderGenericError(user_msg=f"map source not supported: {error}") from error

        _map_source = _source_format.build(
            SourceContext(
                data=self._config.data,
                options=dataclasses.asdict(self._config),
                location=self._get_object_url,
                ranges=(
                    (lambda: self.cached_ranges.at(self.cached_ranges.meta()).read)
                    if self.cached_ranges is not None
                    else (lambda: self.byte_ranges().read)
                ),
            )
        )
        self._map_styles = {
            self._DEFAULT_STYLE_NAME: self._generate_default_map_style(
                _map_source.format, _map_source.content(), _map_source.url()
            ),
            **(dict(self._config.styles)),
        }

    def _get_object_url(self) -> ObjectUrl:
        cached, server = self.cached_ranges, self._range_server
        logger.debug(f"{cached=}, {server=}")
        if cached is not None and server is not None:
            return ObjectUrl(
                resolver=lambda: server.url_for(cached, cached.known_meta() or cached.meta())
            )
        elif self._config.data_url:
            return ObjectUrl(public_url=self._config.data_url)
        elif self._config.data.startswith(("http://", "https://")):
            return ObjectUrl(public_url=self._config.data)
        elif not is_bucket(self._config.data):
            return ObjectUrl(local_path=Path(self._config.data.removeprefix("file://")))
        else:
            raise RuntimeError("Cannot obtain object_url")

    def _generate_default_map_style(
        self,
        source_format: str,
        source_content: "SourceContent",
        source_url: str,
    ) -> dict[str, dict]:
        default_source_name = "dataset"  # name used in default styles to refer to the data source
        if source_content.kind == "vector":
            default_style = generate_default_vector_style(
                vector_layers=source_content.layers,
                source=default_source_name,
                colors=self._config.default_vector_colors,
                background_color=self._config.default_background_color,
            )
        elif source_content.kind == "raster":
            default_style = generate_default_raster_style(
                source=default_source_name,
                background_color=self._config.default_background_color,
            )
        else:  # "raster-dem":
            default_style = generate_default_hillshade_style(
                source=default_source_name,
                background_color=self._config.default_hillshade_background_color,
            )
        url_prefix = "pmtiles://" if source_format == "pmtiles" else ""
        default_style["sources"] = {
            default_source_name: {"type": source_content.kind, "url": f"{url_prefix}{source_url}"}
        }
        return default_style

    def _generate_style(self, style_identifier: str, transparent_background: bool) -> dict | str:
        try:
            style_definition = self._map_styles[style_identifier]
        except KeyError as err:
            raise MapParameterError(user_msg=f"Unknown style {style_identifier}") from err
        if isinstance(style_definition, str):
            # this is a URL to a remote style
            # TODO: retrieve the style from the remote and modify if needed
            return style_definition
        else:
            result = style_definition.copy()
            for background_layer in [
                layer for layer in result.get("layers", []) if layer.get("type") == "background"
            ]:
                layout_definition = background_layer.setdefault("layout", {})
                layout_definition["visibility"] = "none" if transparent_background else "visible"
            return result


def parse_web_mercator_bbox_as_crs84_bbox(
    web_mercator_bbox: Sequence[float],
) -> tuple[float, float, float, float]:
    """Parse a web mercator bbox into a crs84 bbox suitable for feeding into mapli."""
    xmin = web_mercator_bbox[0]
    xmax = web_mercator_bbox[2]

    if xmin > xmax:
        # The west edge lies east of the east edge: bbox crosses the
        # antimeridian, and its east edge is one world further on.
        xmax += 2 * HALF_WORLD

    # clamp y values because web mercator only works correctly
    # when `-HALF_WORLD <= lat <= HALF_WORLD`
    ymin = max(-HALF_WORLD, min(HALF_WORLD, web_mercator_bbox[1]))
    ymax = max(-HALF_WORLD, min(HALF_WORLD, web_mercator_bbox[3]))

    return tuple(
        transform_bbox(
            [xmin, ymin, xmax, ymax],
            from_crs=WEB_MERCATOR,
            to_crs=CRS_84,
            always_xy=True,
        )
    )


def generate_default_vector_style(
    vector_layers: Sequence[str],
    source: str,
    colors: Sequence[str],
    background_color: str = "#ffffff",
) -> dict[str, Any]:
    """Generate a simple vector style for mapli."""
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


def generate_default_raster_style(source: str, background_color: str = "#ffffff") -> dict[str, Any]:
    """Generate a simple raster style for mapli."""
    return {
        "version": 8,
        "sources": {},
        "layers": [
            {
                "id": "background",
                "type": "background",
                "paint": {"background-color": background_color},
            },
            {"id": "raster", "type": "raster", "source": source},
        ],
    }


def generate_default_hillshade_style(
    source: str,
    background_color: str = "#f2efe9",
    shadow_color: str = "#473b24",
    highlight_color: str = "#ffffff",
    accent_color: str = "#6b5b45",
) -> dict[str, Any]:
    """A plain MapLibre style that shades the relief of the elevation ``source``."""
    return {
        "version": 8,
        "sources": {},
        "layers": [
            {
                "id": "background",
                "type": "background",
                "paint": {"background-color": background_color},
            },
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
