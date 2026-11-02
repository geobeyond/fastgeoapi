"""Fastgeoapi provider for OGC API Maps that uses mapli for rendering."""

import asyncio
import copy
import dataclasses
import functools
import hashlib
import importlib.metadata
import json
import math
import threading
from collections.abc import (
    Callable,
    Sequence,
)
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
    ProviderItemNotFoundError,
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
    MapTooLargeError,
    is_bucket,
)
from app.provider.storage import is_remote
from app.provider.storage.base import ObjectChangedError
from app.provider.storage.cache import digest, version_of
from app.provider.storage.ranges import ObjectRanges

if TYPE_CHECKING:
    from app.maps.contract import SourceContent
    from app.provider.storage import CachedRanges
    from app.provider.storage.base import (
        ObjectMeta,
        ObjectStore,
    )
    from app.provider.storage.ranges import ByteRanges

logger = create_logger("app.provider.mapli")

CRS_84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

# north edge of web mercator
MAX_LATITUDE = 85.05112877980659

# URL scheme under which mapli reads bucket data through this module's handler
MAPLI_SCHEME = "fastgeoapi"

# used when computing the version of a map that is to be used for replying to a request
MAPLI_VERSION = importlib.metadata.version("mapli")


class _ObjectVersionReader:
    """Reads bytes from a single version of a bucket object.

    Instances of this class are tied to one version of the object, as
    identified by its ETag, and only ever return bytes of that version.

    Every read is a conditional request (``If-Match``), so a read made after the
    object has been replaced raises ``ObjectChangedError``.

    This class follows the ``ByteRanges`` protocol, like the readers that
    ``CachedRanges`` gives out when the range cache is enabled.
    """

    def __init__(self, store: "ObjectStore", key: str, etag: str) -> None:
        self.store = store
        self.key = key
        self.etag = etag

    def read(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset``."""
        return self.store.get_range(self.key, offset, length, if_match=self.etag)

    async def aread(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset``, asynchronously."""
        return await self.store.aget_range(self.key, offset, length, if_match=self.etag)

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges, in request order."""
        return [self.read(offset, length) for offset, length in ranges]

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges, in request order, asynchronously."""
        return list(await asyncio.gather(*(self.aread(offset, n) for offset, n in ranges)))


class _UncachedObject:
    """Used to access a bucket object when the range cache is disabled.

    This offers the same relevant methods as ``CachedRanges``, but reads every byte
    range directly from the provider's store, without any caching. Its metadata
    is fetched again for every map, so a replaced object is drawn from the next
    map on, and every read is pinned to the version the map was started with.
    """

    store: "ObjectStore"
    key: str
    source: str
    _lock: threading.Lock
    _meta: "ObjectMeta | None"

    def __init__(self, store: "ObjectStore", key: str, *, source: str) -> None:
        """Prepare access to object at ``key`` in ``store``.

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
        """Entry point shared with ``CachedRanges``."""
        return self._get_metadata()

    async def ameta_without_waiting(self) -> "ObjectMeta":
        """Entry point shared with ``CachedRanges``.

        Unlike the ``CachedRanges`` method, this always waits for the store.
        """
        return await self._fetch_metadata()

    def known_meta(self) -> "ObjectMeta | None":
        """Entry point shared with ``CachedRanges``."""
        return self._get_stored_metadata()

    def known(self, version: str) -> "ObjectMeta | None":
        """Entry point shared with ``CachedRanges``."""
        return self._get_metadata_of_version(version)

    def at(self, meta: "ObjectMeta") -> "ByteRanges":
        """Entry point shared with ``CachedRanges``."""
        return self._create_reader(meta)

    def _get_metadata(self) -> "ObjectMeta":
        """Return the stored metadata, fetching it from the store if there is none yet."""
        if (meta := self._get_stored_metadata()) is not None:
            return meta
        return self._store_metadata(self.store.head(self.key))

    async def _fetch_metadata(self) -> "ObjectMeta":
        """Fetch the object's metadata from the store, store it and return it.

        Without a cache there is no known version to trust, so the provider
        calls this before every map, at the cost of one HEAD each time.
        """
        return self._store_metadata(await self.store.ahead(self.key))

    def _get_stored_metadata(self) -> "ObjectMeta | None":
        """Return the metadata fetched last, or None if none has been fetched yet."""
        return self._meta

    def _get_metadata_of_version(self, version: str) -> "ObjectMeta | None":
        """Return the stored metadata if it is of ``version``, or None.

        The scheme handler calls this with the version from a request's URL, to
        check that it serves the version of the object that the style was
        built for.
        """
        meta = self._get_stored_metadata()
        return meta if meta is not None and version_of(meta) == version else None

    def _create_reader(self, meta: "ObjectMeta") -> "ByteRanges":
        """Create a reader of byte ranges of the object at the version ``meta`` names.

        The reads go straight to the store. An object without an ETag has no
        version to pin to, so its reads return the object's current bytes.
        """
        if meta.etag is None:
            return ObjectRanges(self.store, self.key)
        return _ObjectVersionReader(self.store, self.key, meta.etag)

    def _store_metadata(self, meta: "ObjectMeta") -> "ObjectMeta":
        """Store ``meta`` as the object's current metadata, and return it.

        Only the latest version is kept: a map still being drawn from an older
        one fails its reads anyway, since the object has changed since.
        """
        with self._lock:
            self._meta = meta
            return meta


type _SchemeObject = CachedRanges | _UncachedObject


class _MapliSchemeHandler:
    """mapli scheme handler for ``fastgeoapi://<source>/<version>`` URLs.

    This is a custom mapli scheme handler. It serves `fastgeoapi://` URLs. mapli
    calls it and expects the raw data bytes in return. The implementation uses the
    fastgeoapi store to retrieve the data and pass it back to mapli.

    This is useful because:

    - data in private buckets can only be accessed by using authentication, and
      the fastgeoapi store already knows how to provide auth details, while
      vanilla mapli (which uses MapLibre Native) does not.

    - data stored in remote object stores benefits from being cached. When the
      range cache is enabled, the handler reads through it, so that a byte
      range fetched from the bucket is reused until it is evicted from the cache
      or the data changes. With the range cache turned off, every byte range is
      fetched from the bucket.
    """

    _sources: dict[str, _SchemeObject]

    def __init__(self) -> None:
        self._sources = {}

    def register_source(self, source: _SchemeObject) -> None:
        """Make ``source`` available to mapli through this handler.

        ``source`` gives access to a provider's data, either through the range
        cache (``CachedRanges``) or straight from the store (``_UncachedObject``).
        """
        self._sources[source.source] = source

    def generate_scheme_url(self, scheme_object: _SchemeObject, meta: "ObjectMeta") -> str:
        """Generate the URL that mapli uses to read ``scheme_object``'s data.

        The URL has the form ``fastgeoapi://<source>/<version>``, where ``source``
        is the digest of the provider's ``data`` and ``version`` is derived from
        the ETag in ``meta``. It names the data without revealing its real
        location or any credentials.
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
    min_image_width: int = 1
    max_image_width: int = 2048
    min_image_height: int = 1
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


@dataclasses.dataclass(frozen=True)
class _MapArguments:
    """The arguments of a map request, checked and ready for rendering."""

    style_id: str
    lon_lat_bbox: tuple[float, float, float, float]
    width: int
    height: int
    transparent: bool


@dataclasses.dataclass(frozen=True)
class _MapStyles:
    """The styles to draw maps with, for one version of the data.

    ``data_version`` is None when the version of the data is not known.
    ``dataset_url`` is the URL mapli reads that version of the data at.
    """

    data_version: str | None
    styles: dict[str, str | dict]
    dataset_url: str


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
    _map_styles: _MapStyles | None
    _map_styles_lock: threading.Lock

    def __init__(self, provider_def: dict) -> None:
        super().__init__(provider_def)
        self._config = MapliMapProviderConfig.from_pygeoapi_provider_def(provider_def)
        self._map_styles = None
        self._map_styles_lock = threading.Lock()
        if Path(urlsplit(self._config.data).path).suffix.lower() != ".pmtiles":
            raise ProviderGenericError(user_msg=f"map source not supported: {self._config.data}")

    async def aversion(self, **kwargs: Any) -> str | None:
        """Entry point of fastgeoapi's VersionedProvider protocol."""
        return await self._compute_map_version(**kwargs)

    async def aquery(self, **kwargs: Any) -> bytes:
        """Entry point of fastgeoapi's async map provider interface."""
        return await self._render_map(**kwargs)

    def query(self, **kwargs: Any) -> bytes:
        """Entry point of pygeoapi's map provider interface."""
        return asyncio.run(self._render_map(**kwargs))

    async def _fetch_data_version(self) -> str | None:
        """Fetch the version of the provider's data; None when it is unknown.

        Remote data read through the range cache has the ETag the cache knows.
        A bucket read without it has the ETag the store gives now, as its
        metadata is fetched for every map anyway. Remote data that mapli reads
        itself has no version. Local data has its size and modification time.
        """
        scheme_object = self._scheme_object
        if isinstance(scheme_object, _UncachedObject):
            return (await scheme_object.ameta_without_waiting()).etag
        return await self.adata_version()

    def _compute_definition_digest(self) -> str:
        """Compute a digest of the provider's definition.

        Any change to the configuration of the provider, its options included,
        changes the digest. Credentials in ``store_options`` never leave the
        computation: only the digest is returned.
        """
        return self.definition_digest()

    async def _compute_map_version(
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
        """Determine the map version that would be used for rendering.

        This method can be used to help decide whether a map needs to be
        re-rendered or if a cached version can be used instead. It computes
        a unique string based on the data version, style definition, and
        other parameters.

        If the data version is unknown (e.g., when using remote
        data without a range cache), it returns None, indicating that the
        version cannot be determined.

        The output of this can be used by fastgeoapi's HTTP caching
        mechanism to build suitable ETag headers and also to decide whether to
        render a map image to return to clients, or just return a 304 Not
        Modified answer.

        NOTE: A style given as a URL is identified by its URL only, so a
        change to the document at that URL does not change the version.

        NOTE: The data version is looked up here and again when the map is
        rendered. If the data is replaced in between, the version returned here
        names the previous data while the map is drawn from the new data.
        """
        if (data_version := await self._fetch_data_version()) is None:
            return None
        arguments = self._validate_arguments(
            style=style,
            bbox=bbox,
            width=width,
            height=height,
            crs=crs,
            transparent=transparent,
            format_=format_,
        )
        # uses run_sync as getting the style identifier may involve reading data and its version
        style_identifier, _ = await self.run_sync(
            self._generate_registered_style, arguments.style_id, arguments.transparent
        )
        return "|".join(
            (data_version, self._compute_definition_digest(), style_identifier, MAPLI_VERSION)
        )

    async def _render_map(
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
        arguments = self._validate_arguments(
            style=style,
            bbox=bbox,
            width=width,
            height=height,
            crs=crs,
            transparent=transparent,
            format_=format_,
        )

        scheme_object = self._scheme_object
        if scheme_object is not None:
            # Register only once the version is known: on a reload, the provider
            # this one replaces keeps serving its maps until then
            await scheme_object.ameta_without_waiting()
            _SCHEME_HANDLER.register_source(scheme_object)

        registered_style_identifier = await self.run_sync(
            self._register_style, self._render_pool, arguments.style_id, arguments.transparent
        )
        try:
            return await self._render_pool.arender_from_bounds(
                style_id=registered_style_identifier,
                bbox=arguments.lon_lat_bbox,
                width=arguments.width,
                height=arguments.height,
            )
        except mapli.StyleLoadError as error:
            logger.warning(f"mapli could not load style {arguments.style_id!r}: {error}")
            raise ProviderGenericError(
                user_msg=f"style {arguments.style_id} could not be loaded"
            ) from error
        except mapli.MapliError as error:
            logger.warning(f"mapli failed to render with {type(error).__name__}: {error}")
            raise ProviderGenericError(user_msg="the map renderer failed") from error

    def _validate_arguments(
        self,
        style: str | None,
        bbox: list[float] | None,
        width: int,
        height: int,
        crs: str | None,
        transparent: Any,
        format_: str | None,
    ) -> _MapArguments:
        """Check the arguments of a map request and return them ready for rendering.

        Both ``compute_map_version`` and ``render_map`` call this first, so a
        request that ``render_map`` refuses never gets a version. It reads nothing: an unknown
        style is found later, when the style is generated.
        """
        if format_ not in ("png", "html"):
            raise MapParameterError(user_msg="maps are drawn as PNG only")

        # The `transparent` query param may arrive as the string of the request:
        # pygeoapi's route passes it on as is, and so does fastgeoapi's async
        # route until https://github.com/geobeyond/fastgeoapi/issues/491 is fixed
        if isinstance(transparent, bool):
            with_transparency = transparent
        elif isinstance(transparent, str) and transparent.lower() in ("true", "false"):
            with_transparency = transparent.lower() == "true"
        else:
            raise MapParameterError(user_msg="'transparent' must be either true or false")

        if width < self._config.min_image_width:
            raise MapParameterError(
                user_msg=f"Please provide a width of at least {self._config.min_image_width}"
            )
        if width > self._config.max_image_width:
            raise MapTooLargeError(
                user_msg=f"Please provide a width of at most {self._config.max_image_width}"
            )
        if height < self._config.min_image_height:
            raise MapParameterError(
                user_msg=f"Please provide a height of at least {self._config.min_image_height}"
            )
        if height > self._config.max_image_height:
            raise MapTooLargeError(
                user_msg=f"Please provide a height of at most {self._config.max_image_height}"
            )

        effective_crs = crs or WEB_MERCATOR
        if effective_crs.lower() != WEB_MERCATOR.lower():
            raise MapParameterError(user_msg=f"maps are drawn in {WEB_MERCATOR} only")

        web_mercator_bbox = (
            [float(i) for i in bbox] if bbox else (-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD)
        )
        if any(math.isnan(i) for i in web_mercator_bbox):
            raise MapParameterError(user_msg="bounding box contains NaN values")
        west, south, east, north = parse_web_mercator_bbox_as_crs84_bbox(web_mercator_bbox)
        # mapli refuses a bbox without area, which includes one lying entirely
        # beyond the poles, as its latitudes are clamped to the same value. A
        # west edge east of the east edge is fine: the bbox crosses the antimeridian
        if west == east or south >= north:
            raise MapParameterError(user_msg="bounding box must have a positive width and height")

        return _MapArguments(
            style_id=style or self._config.default_style or self._DEFAULT_STYLE_NAME,
            lon_lat_bbox=(west, south, east, north),
            width=width,
            height=height,
            transparent=with_transparency,
        )

    def _register_style(
        self, render_pool: mapli.RenderPool, style_id: str, transparent_background: bool
    ) -> str:
        """Register the style with mapli, if needed, and return its identifier there."""
        registered_style_identifier, style_definition = self._generate_registered_style(
            style_id, transparent_background
        )
        if not render_pool.has_style(registered_style_identifier):
            if isinstance(style_definition, str):
                render_pool.register_style(registered_style_identifier, url=style_definition)
            else:
                render_pool.register_style(registered_style_identifier, json=style_definition)
        return registered_style_identifier

    def _generate_registered_style(
        self, style_id: str, transparent_background: bool
    ) -> tuple[str, dict | str]:
        """Generate the style and the identifier mapli registers it under.

        The identifier changes along with the style's contents, including the URL of
        the data, which names its version when read through the scheme handler. When
        the data changes, a new style gets registered instead of drawing the old version.
        A style given as a URL is registered under its name.
        """
        style_definition = self._generate_style(
            style_id, transparent_background=transparent_background
        )
        if isinstance(style_definition, str):
            return style_id, style_definition
        serialized = json.dumps(style_definition, sort_keys=True)
        style_digest = hashlib.sha256(serialized.encode()).hexdigest()[:16]
        return f"{style_id}-{style_digest}", style_definition

    @functools.cached_property
    def _render_pool(self) -> mapli.RenderPool:
        """Create mapli render pool.

        This is implemented as a cached property in order to ensure the render
        pool is not created during provider initialization, as that could cause
        unneeded slowdowns - providers may be initialized multiple times
        during the app lifecycle (ex: generating the openapi document), and
        not always in order to render maps.

        A mapli render pool starts some additional GL threads.
        """
        return mapli.RenderPool(
            workers=self._config.num_workers,
            max_renderers_per_worker=self._config.max_renderers_per_worker,
        )

    def _get_map_styles(self) -> _MapStyles:
        """Return the styles to draw maps with, for the current version of the data.

        The styles are generated again whenever the version of the data changes.
        The default style, its dataset URL and the version all come from the same
        metadata of the data.
        """
        scheme_object = self._scheme_object
        if scheme_object is not None:
            meta = scheme_object.known_meta() or scheme_object.meta()
            data_version = version_of(meta)
            read_data = scheme_object.at(meta).read
            dataset_url = _SCHEME_HANDLER.generate_scheme_url(scheme_object, meta)
        else:
            data_version = self._get_direct_data_version()
            read_data = self.byte_ranges().read
            dataset_url = self._generate_direct_dataset_url()
        with self._map_styles_lock:
            map_styles = self._map_styles
            if map_styles is None or map_styles.data_version != data_version:
                map_styles = self._map_styles = _MapStyles(
                    data_version=data_version,
                    styles=self._generate_map_styles(read_data),
                    dataset_url=f"pmtiles://{dataset_url}",
                )
            return map_styles

    def _get_direct_data_version(self) -> str | None:
        """Get the version of data that mapli reads itself; None when it is unknown.

        Local data has its size and modification time. Remote data has no
        known version, since finding it would cost a HEAD for every map.
        """
        if is_remote(self._config.data):
            return None
        meta = self.store.head(self.object_key)
        modified = meta.last_modified.isoformat() if meta.last_modified is not None else ""
        return f"{meta.size}:{modified}"

    def _generate_map_styles(self, read_data: Callable[[int, int], bytes]) -> dict[str, str | dict]:
        """Generate the default style, from what the archive holds, and add the configured styles.

        Generating the default style means reading the archive's header and
        metadata, through ``read_data``.
        """
        map_source = PMTilesSource(
            # PMTilesSource needs a location, but reading its content does not use it
            ObjectUrl(public_url=self._config.data),
            read_data,
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
        """The object mapli reads through the scheme handler.

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
        map_styles = self._get_map_styles()
        try:
            style_definition = map_styles.styles[style_identifier]
        except KeyError as err:
            raise ProviderItemNotFoundError(user_msg=f"Unknown style {style_identifier}") from err
        if isinstance(style_definition, str):
            # this is a URL to a remote style
            # TODO: retrieve the style from the remote and modify if needed
            return style_definition
        else:
            result = copy.deepcopy(style_definition)
            dataset_source = result.get("sources", {}).get(self._DATASET_SOURCE_NAME)
            if dataset_source is not None and "url" not in dataset_source:
                dataset_source["url"] = map_styles.dataset_url
            for background_layer in [
                layer for layer in result.get("layers", []) if layer.get("type") == "background"
            ]:
                layout_definition = background_layer.setdefault("layout", {})
                layout_definition["visibility"] = "none" if transparent_background else "visible"
            return result

    def _generate_direct_dataset_url(self) -> str:
        """Generate the URL of data that mapli reads itself, rather than through the scheme handler.

        That is the ``data_url``, the data's http(s) URL or its local path.
        """
        if self._config.data_url:
            return self._config.data_url
        if self._config.data.startswith(("http://", "https://")):
            return self._config.data
        return f"file://{Path(self._config.data.removeprefix('file://')).resolve()}"


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
