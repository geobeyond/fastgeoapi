"""Fastgeoapi provider for OGC API Maps that uses mapli for rendering."""

import asyncio
import copy
import dataclasses
import functools
import hashlib
import json
import math
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
)
from urllib.parse import urlsplit

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
    PMTilesSource,
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
from app.provider.storage.base import ObjectChangedError
from app.provider.storage.cache import digest, version_of
from app.provider.storage.ranges import ObjectRanges

if TYPE_CHECKING:
    from app.maps.contract import SourceContent
    from app.provider.storage import CachedRanges
    from app.provider.storage.base import ObjectMeta, ObjectStore
    from app.provider.storage.ranges import ByteRanges

logger = create_logger("app.provider.mapli")

CRS_84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

# The highest latitude mapli draws: the north edge of web mercator
MAX_LATITUDE = 85.05112877980659

# URL scheme under which mapli reads bucket data through this module's handler
MAPLI_SCHEME = "fastgeoapi"


class _UncachedObject:
    """Gives the scheme handler access to a bucket object when the range cache is off.

    This offers the same relevant methods as ``CachedRanges``, but reads every byte
    range directly from the provider's store (authenticated with its ``store_options``),
    without any caching.
    """

    def __init__(self, store: "ObjectStore", key: str, *, source: str) -> None:
        """Prepare access to the object at ``key`` in ``store``, without any I/O yet.

        ``source`` is the provider's ``data``. Its digest becomes this object's
        ``source`` attribute, which identifies the object in the URLs the scheme
        handler serves.
        """
        self.store = store
        self.key = key
        self.source = digest(source)
        self._meta: ObjectMeta | None = None
        self._lock = threading.Lock()

    def meta(self) -> "ObjectMeta":
        """Return the object's metadata, fetching it with a HEAD request on first use."""
        meta = self.known_meta()
        if meta is not None:
            return meta
        return self._register_metadata(self.store.head(self.key))

    async def ameta_without_waiting(self) -> "ObjectMeta":
        """Return the object's metadata, fetching it asynchronously on first use.

        The name matches the method of ``CachedRanges`` that the provider calls
        before each render. Here, only the first call waits for the store, since
        the metadata is never refreshed afterwards.
        """
        meta = self.known_meta()
        if meta is not None:
            return meta
        return self._register_metadata(await self.store.ahead(self.key))

    def known_meta(self) -> "ObjectMeta | None":
        """Return the object's metadata if it has been fetched already, or None."""
        return self._meta

    def known(self, version: str) -> "ObjectMeta | None":
        """Return the object's metadata if ``version`` matches it, or None.

        The scheme handler calls this with the version from a request's URL, to
        check that it serves the version of the object that the style was
        built for.
        """
        meta = self.known_meta()
        return meta if meta is not None and version_of(meta) == version else None

    def at(self, meta: "ObjectMeta") -> "ByteRanges":
        """Return a reader of byte ranges of the object, straight from the store.

        ``meta`` is accepted to match ``CachedRanges.at`` but not used: the reads
        are not tied to a version, so they return the object's current bytes.
        """
        return ObjectRanges(self.store, self.key)

    def _register_metadata(self, meta: "ObjectMeta") -> "ObjectMeta":
        """Store ``meta`` unless metadata is already stored, and return the stored one.

        Two maps rendered concurrently can both fetch the metadata before either
        stores it. The lock makes the first one to be stored win, so that every
        caller gets the same version.
        """
        with self._lock:
            if self._meta is None:
                self._meta = meta
            return self._meta


type _SchemeObject = CachedRanges | _UncachedObject


class _MapliSchemeHandler:
    """mapli scheme handler for ``fastgeoapi://<source>/<version>`` URLs.

    This is a custom mapli scheme handler. It serves `fastgeoapi://` URLs. mapli
    calls it and expects the raw data bytes in return. The implementation uses the
    fastgeoapi store to retrieve the data and pass it back to mapli.

    This is useful because:

    - data in private buckets can only be accessed by using authentication, and
      the fastgeoapi store already knows how to provide auth details, while
      vanilla mapli (which uses MapLibre Native) does not

    - data stored in remote object stores benefits from being cached. The
      fastgeoapi store itself does not cache anything, but when the range cache
      is enabled the handler reads through it (``CachedRanges``), so that a byte
      range fetched from the bucket is reused until it is evicted from the cache
      or the data changes. With the range cache turned off, every byte range is
      fetched from the bucket (``_UncachedObject``)
    """

    _sources: dict[str, _SchemeObject]

    def __init__(self) -> None:
        self._sources = {}

    def register_source(self, source: _SchemeObject) -> None:
        """Make ``source`` available to mapli through this handler.

        ``source`` gives access to a provider's data, either through the range
        cache (``CachedRanges``) or straight from the store (``_UncachedObject``).
        It is stored under its ``source`` attribute, the digest of the provider's
        ``data``, which is the key that appears in the URLs built by
        :meth:`generate_scheme_url`. When mapli requests one of those URLs,
        :meth:`__call__` uses that key to find this object and read the requested
        bytes from it.
        """
        self._sources[source.source] = source

    def generate_scheme_url(self, scheme_object: _SchemeObject, meta: "ObjectMeta") -> str:
        """Generate the URL that mapli uses to read ``scheme_object``'s data.

        The URL has the form ``fastgeoapi://<source>/<version>``, where ``source``
        is the digest of the provider's ``data`` and ``version`` is derived from
        the ETag in ``meta``. It names the data without revealing its real
        location or any credentials. The provider puts this URL in the dataset
        source of the styles it registers with mapli (prefixed with
        ``pmtiles://`` for PMTiles archives).
        """
        return f"{MAPLI_SCHEME}://{scheme_object.source}/{version_of(meta)}"

    def __call__(self, request: mapli.ResourceRequest) -> mapli.Response | bytes:
        """Serve a read that mapli makes for a URL built by :meth:`generate_scheme_url`.

        The requested (inclusive) byte range is turned into an offset and length and
        clamped to the object's size; a request without a range reads the whole
        object. The bytes are read synchronously, through the range cache or
        straight from the store, and returned as is.
        """
        parts = urlsplit(request.url)
        source, version = parts.netloc, parts.path.strip("/")
        scheme_object = self._sources.get(source)
        meta = scheme_object.known(version) if scheme_object is not None else None
        if scheme_object is None or meta is None:
            return mapli.Response.error(mapli.ErrorReason.NOT_FOUND, f"unknown data {request.url}")
        if request.data_range is None:
            offset, end = 0, meta.size - 1
        else:
            offset, end = request.data_range
        if offset >= meta.size:
            return mapli.Response.error(
                mapli.ErrorReason.NOT_FOUND, f"range starts past the end of {request.url}"
            )
        length = min(end, meta.size - 1) - offset + 1
        try:
            return scheme_object.at(meta).read(offset, length)
        except ObjectChangedError:
            # The object changed under a version mapli still holds
            return mapli.Response.error(mapli.ErrorReason.NOT_FOUND, f"{request.url} has changed")
        except Exception as error:
            logger.warning(f"mapli range read failed with {type(error).__name__}: {error}")
            return mapli.Response.error(mapli.ErrorReason.SERVER, "the data could not be read")


_SCHEME_HANDLER = _MapliSchemeHandler()
mapli.register_scheme_handler(MAPLI_SCHEME, _SCHEME_HANDLER)


@dataclasses.dataclass(frozen=True)
class MapliMapProviderConfig:
    """Configuration for mapli provider.

    This only contains the configuration parameters that the MapliMapProvider actually needs.
    """

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
    # NOTE: It will be non-None if this provider's configured `data` points to
    # a remote resource and if the provider's configured `options.range_cache`
    # is not set to False. When it has a value, `_scheme_object` makes mapli
    # read the data through it
    cached_ranges: "CachedRanges | None"

    _DEFAULT_STYLE_NAME = "default"

    _DATASET_SOURCE_NAME = "dataset"

    _config: MapliMapProviderConfig

    def __init__(self, provider_def: dict) -> None:
        super().__init__(provider_def)
        self._config = MapliMapProviderConfig.from_pygeoapi_provider_def(provider_def)
        if Path(urlsplit(self._config.data).path).suffix.lower() != ".pmtiles":
            raise ProviderGenericError(user_msg=f"map source not supported: {self._config.data}")

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

        scheme_object = self._scheme_object
        if scheme_object is not None:
            # Register only once the version is known: on a reload, the provider
            # this one replaces keeps serving its maps until then
            await scheme_object.ameta_without_waiting()
            _SCHEME_HANDLER.register_source(scheme_object)

        style_id = style or self._config.default_style or self._DEFAULT_STYLE_NAME
        # In a thread: preparing the style may read the data and its version
        registered_style_identifier = await self.run_sync(
            self._register_style, self._render_pool, style_id, with_transparency
        )
        try:
            return await self._render_pool.arender_from_bounds(
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
        the data, which names its version when read through the scheme handler. When
        the data changes, a new style gets registered instead of drawing the old version.
        """
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

    @functools.cached_property
    def _render_pool(self) -> mapli.RenderPool:
        """Create the pool on the first map, so that building the provider starts no GL threads."""
        return mapli.RenderPool(
            workers=self._config.num_workers,
            max_renderers_per_worker=self._config.max_renderers_per_worker,
        )

    @functools.cached_property
    def _map_styles(self) -> dict[str, str | dict]:
        """The styles this provider draws with, by name: the default one and the configured ones.

        The default style is generated from what the archive holds, which means
        reading its header and metadata. This is why the styles are computed at
        the first map rather than in the constructor, which must not do any I/O.
        """
        map_source = PMTilesSource(
            # PMTilesSource needs a location, but reading its content does not use it
            ObjectUrl(public_url=self._config.data),
            self._get_byte_range_reader(),
            dem=self._config.dem_data_encodings,
        )
        try:
            source_content = map_source.content()
        except ImportError as error:
            raise ProviderGenericError(user_msg=f"map source not available: {error}") from error
        except SourceNotDrawableError as error:
            raise ProviderGenericError(user_msg=f"map source not drawable: {error}") from error
        return {
            self._DEFAULT_STYLE_NAME: self._generate_default_map_style(source_content),
            **(dict(self._config.styles)),
        }

    @functools.cached_property
    def _scheme_object(self) -> _SchemeObject | None:
        """The object mapli reads through the scheme handler; None when it reads by URL.

        mapli (and thus MapLibre Native) has no bucket credentials, so data in a
        bucket is read through the handler, with the store and its store_options:
        through the range cache when it applies, else straight from the store.
        A data_url, when given, is read directly instead, unless the range cache
        applies.
        """
        if self.cached_ranges is not None:
            return self.cached_ranges
        if is_bucket(self._config.data) and self._config.data_url is None:
            return _UncachedObject(self.store, self.object_key, source=self._config.data)
        return None

    def _get_byte_range_reader(self) -> Callable[[int, int], bytes]:
        """Return the reader that the map source uses to parse the archive.

        Data read through the scheme handler is parsed through the same scheme
        object that the handler serves, so the parsed header and metadata match
        the version of the data that mapli reads. Any other data is read through
        the provider's store.
        """
        scheme_object = self._scheme_object
        if scheme_object is not None:
            return scheme_object.at(scheme_object.meta()).read
        return self.byte_ranges().read

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
        """Generate the URL that mapli reads the data at, for the dataset source of a style.

        Data read through the scheme handler gets a ``fastgeoapi://`` URL that names
        its current version. Any other data is read by mapli itself, at its
        ``data_url``, its http(s) URL or its local path.
        """
        scheme_object = self._scheme_object
        if scheme_object is not None:
            meta = scheme_object.known_meta() or scheme_object.meta()
            url = _SCHEME_HANDLER.generate_scheme_url(scheme_object, meta)
        elif self._config.data_url:
            url = self._config.data_url
        elif self._config.data.startswith(("http://", "https://")):
            url = self._config.data
        else:
            url = f"file://{Path(self._config.data.removeprefix('file://')).resolve()}"
        return f"pmtiles://{url}"


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
