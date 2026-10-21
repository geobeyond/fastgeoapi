"""Fastgeoapi provider for OGC API Maps that uses mapli for rendering."""

import asyncio
import copy
import dataclasses
import hashlib
import json
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
from app.maps.contract import SourceNotDrawableError
from app.maps.sources import (
    ObjectUrl,
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
    from app.maps.contract import MapSource, SourceContent
    from app.provider.storage import CachedRanges
    from app.provider.storage.loopback import RangeServer

logger = create_logger("app.provider.mapli")

CRS_84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

# The highest latitude mapli draws: the north edge of web mercator
MAX_LATITUDE = 85.05112877980659


@dataclasses.dataclass(frozen=True)
class MapliMapProviderConfig:
    """Configuration for mapli provider."""

    _supported_dem_encodings: ClassVar[list[str]] = ["mapbox", "terrarium"]

    data: str
    # Each worker is a thread with its own renderers, each renderer has its own
    # GL context and tile cache: keep these low on slim nodes
    num_workers: int = 1
    max_renderers_per_worker: int = 4
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
        if self.dem_data_encodings and self.dem_data_encodings not in self._supported_dem_encodings:
            raise ProviderGenericError(
                user_msg=(
                    f"dem must be one of {self._supported_dem_encodings!r}, "
                    f"not {self.dem_data_encodings!r}"
                )
            )

    @classmethod
    def from_pygeoapi_provider_def(cls, provider_def: dict) -> "MapliMapProviderConfig":
        """Generate an instance from a pygeoapi provider definition dictionary."""
        options = provider_def.get("options") or {}
        return cls(
            data=provider_def["data"],
            data_url=options.get("data_url", cls.data_url),
            dem_data_encodings=options.get("dem", cls.dem_data_encodings),
            max_renderers_per_worker=options.get(
                "max_renderers_per_worker", cls.max_renderers_per_worker
            ),
            num_workers=options.get("num_workers", cls.num_workers),
            storage_crs=provider_def.get("storage_crs", cls.storage_crs),
            store_options=provider_def.get("store_options", cls.store_options),
            styles=options.get("styles") or {},
            default_style=options.get("default_style", cls.default_style),
            default_background_color=options.get(
                "default_background_color", cls.default_background_color
            ),
            default_vector_colors=tuple(
                options.get("default_vector_colors", cls.default_vector_colors)
            ),
            default_hillshade_background_color=options.get(
                "default_hillshade_background_color", cls.default_hillshade_background_color
            ),
            min_image_width=options.get("min_image_width", cls.min_image_width),
            max_image_width=options.get(
                "max_image_width", options.get("max_size", cls.max_image_width)
            ),
            min_image_height=options.get("min_image_height", cls.min_image_height),
            max_image_height=options.get(
                "max_image_height", options.get("max_size", cls.max_image_height)
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

    # Name used in styles to refer to the collection's data. When a style declares
    # this source without a `url`, the provider fills in the current URL of the data
    _DATASET_SOURCE_NAME = "dataset"

    # Configuration explicitly used by this provider
    _config: MapliMapProviderConfig

    # The fastgeoapi local http cache server which may be used as a local http cache
    _range_server: "RangeServer | None"

    _render_pool: mapli.RenderPool | None
    _map_source: "MapSource | None"
    _map_styles: dict[str, str | dict]

    def __init__(self, provider_def: dict) -> None:
        super().__init__(provider_def)
        self._range_server = None
        self._config = MapliMapProviderConfig.from_pygeoapi_provider_def(provider_def)
        if self._config.data_url is None and is_bucket(self._config.data):
            # NOTE: mapli (and thus MapLibre Native, which it uses) fetches the
            # data itself, by URL, without bucket credentials. This means that
            # a bucket can be read either:
            # - through the range cache's loopback server, which reads it
            #   with the credentials, or
            # - at a public data_url.
            #
            # Private buckets are thus only supported with the range cache
            # enabled, because its loopback server reads the bucket through
            # fastgeoapi's store, which is able to authenticate with the
            # provider's store_options.
            #
            # Providing a presigned URL of the object would be another way
            # to give mapli access to a private bucket without the range cache,
            # but it is deliberately not supported: a presigned URL expires, so it
            # would have to be signed again periodically (e.g. every hour), and
            # each new URL would amount to registering a new style in mapli. It
            # would also put a secret in the style.
            #
            # To use a private bucket without the range cache, run a proxy that
            # signs requests to the bucket with its own credentials (e.g.
            # aws-sigv4-proxy) and point data_url at it.
            should_use_local_cache = (
                provider_def.get("options", {}).get("range_cache", True) and range_cache_enabled()
            )
            if not should_use_local_cache:
                raise ProviderGenericError(
                    user_msg=(
                        "data in a bucket needs either the range cache or options.data_url, "
                        "the https URL of the data"
                    )
                )

        try:
            self._source_format = source_for(self._config.data)
        except LookupError as error:
            raise ProviderGenericError(user_msg=f"map source not supported: {error}") from error

        # Cannot create default styles yet: that reads the data, and the
        # constructor must not do any I/O
        self._map_source = None
        self._map_styles = {}
        self._render_pool = None

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
            raise MapParameterError(user_msg="bounding box contains NaN values")
        lon_lat_bbox = parse_web_mercator_bbox_as_crs84_bbox(web_mercator_bbox)

        cached = self.cached_ranges
        if cached is not None:
            self._range_server = await ensure_range_server()
            # Register only once the version is known: on a reload, the provider
            # this one replaces keeps serving its maps until then
            await cached.ameta_without_waiting()
            SOURCES.register(cached)

        if self._render_pool is None:
            self._render_pool = mapli.RenderPool(
                workers=self._config.num_workers,
                max_renderers_per_worker=self._config.max_renderers_per_worker,
            )
        render_pool = self._render_pool

        style_id = style or self._config.default_style or self._DEFAULT_STYLE_NAME
        # In a thread: preparing the style may read the data and its version
        registered_style_identifier = await self.run_sync(
            self._register_style, render_pool, style_id, with_transparency
        )
        try:
            return await render_pool.arender_from_bounds(
                style_id=registered_style_identifier,
                bbox=lon_lat_bbox,
                width=width,
                height=height,
            )
        except mapli.StyleLoadError as error:
            logger.warning(f"mapli could not load style {style_id!r}: {error}")
            raise ProviderGenericError(user_msg=f"style {style_id} could not be loaded") from error
        except mapli.MapliError as error:
            logger.warning(f"mapli failed to render with {type(error).__name__}: {error}")
            raise ProviderGenericError(user_msg="the map renderer failed") from error

    def query(self, **kwargs: Any) -> bytes:
        """Generate a map image."""
        return asyncio.run(self.aquery(**kwargs))

    def _register_style(
        self, render_pool: mapli.RenderPool, style_id: str, transparent_background: bool
    ) -> str:
        """Register the style with mapli, if needed, and return its identifier there.

        The identifier changes along with the style's contents, including the URL of
        the data, which names its version when read through the range cache. When the
        data changes, a new style gets registered instead of drawing the old version.
        """
        if len(self._map_styles) == 0:  # this is the first time we are running
            self._initialize_styles()
        style_definition = self._generate_style(
            style_id, transparent_background=transparent_background
        )
        if isinstance(style_definition, str):
            registered_style_identifier = style_id
        else:
            serialized = json.dumps(style_definition, sort_keys=True)
            digest = hashlib.sha256(serialized.encode()).hexdigest()[:16]
            registered_style_identifier = f"{style_id}-{digest}"
        if not render_pool.has_style(registered_style_identifier):
            if isinstance(style_definition, str):
                render_pool.register_style(registered_style_identifier, url=style_definition)
            else:
                render_pool.register_style(registered_style_identifier, json=style_definition)
        return registered_style_identifier

    def _initialize_styles(self) -> None:
        # NOTE: these lambdas are called right away, while building the source, so the
        # source does not end up holding a reference to `self`. Keeping it that way
        # avoids a reference cycle, which would delay freeing the render pool on reload
        cached = self.cached_ranges
        try:
            self._map_source = self._source_format.build(
                SourceContext(
                    data=self._config.data,
                    options={"dem": self._config.dem_data_encodings},
                    location=self._get_object_url,
                    ranges=(
                        (lambda: cached.at(cached.meta()).read)
                        if cached is not None
                        else (lambda: self.byte_ranges().read)
                    ),
                )
            )
            source_content = self._map_source.content()
        except ImportError as error:
            raise ProviderGenericError(user_msg=f"map source not available: {error}") from error
        except SourceNotDrawableError as error:
            raise ProviderGenericError(user_msg=f"map source not drawable: {error}") from error
        self._map_styles = {
            self._DEFAULT_STYLE_NAME: self._generate_default_map_style(source_content),
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

    def _generate_default_map_style(self, source_content: "SourceContent") -> dict[str, Any]:
        """Generate the default style, with the data source but not its URL yet."""
        if source_content.kind == "vector":
            default_style = generate_default_vector_style(
                vector_layers=source_content.layers,
                source=self._DATASET_SOURCE_NAME,
                colors=self._config.default_vector_colors,
                background_color=self._config.default_background_color,
            )
        elif source_content.kind == "raster":
            default_style = generate_default_raster_style(
                source=self._DATASET_SOURCE_NAME,
                background_color=self._config.default_background_color,
            )
        else:  # "raster-dem":
            default_style = generate_default_hillshade_style(
                source=self._DATASET_SOURCE_NAME,
                background_color=self._config.default_hillshade_background_color,
            )
        dataset_source: dict[str, Any] = {"type": source_content.kind}
        if source_content.tile_size:
            # MapLibre assumes 512 pixel raster tiles unless told otherwise
            dataset_source["tileSize"] = source_content.tile_size
        if source_content.dem:
            dataset_source["encoding"] = source_content.dem
        default_style["sources"] = {self._DATASET_SOURCE_NAME: dataset_source}
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
            result = copy.deepcopy(style_definition)
            dataset_source = result.get("sources", {}).get(self._DATASET_SOURCE_NAME)
            if dataset_source is not None and "url" not in dataset_source:
                dataset_source["url"] = self._generate_dataset_url()
            for background_layer in [
                layer for layer in result.get("layers", []) if layer.get("type") == "background"
            ]:
                layout_definition = background_layer.setdefault("layout", {})
                layout_definition["visibility"] = "none" if transparent_background else "visible"
            return result

    def _generate_dataset_url(self) -> str:
        """Generate the URL of the data as it is now, which may name its current version."""
        if self._map_source is None:
            raise RuntimeError("the styles have not been initialized yet")
        url_prefix = "pmtiles://" if self._map_source.format == "pmtiles" else ""
        return f"{url_prefix}{self._map_source.url()}"


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

    west, south, east, north = transform_bbox(
        [xmin, ymin, xmax, ymax],
        from_crs=WEB_MERCATOR,
        to_crs=CRS_84,
        always_xy=True,
    )
    # The edge of web mercator comes back a hair beyond the latitude mapli accepts
    south = max(-MAX_LATITUDE, min(MAX_LATITUDE, south))
    north = max(-MAX_LATITUDE, min(MAX_LATITUDE, north))
    return west, south, east, north


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
