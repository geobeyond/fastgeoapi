"""Fastgeoapi's provider protocols, one per family.

A provider class takes the native path by setting ``native_async = True``;
any other provider is served by pygeoapi. A class matches a Protocol by
its members, whether or not it inherits from fastgeoapi's mixin.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Any, ClassVar, Protocol, runtime_checkable

from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon

from app.interfaces.ogc import EDR_CONFORMANCE_PREFIXES, MAPS_CONFORMANCE_PREFIX
from app.schemas.temporal import TimeInterval


@runtime_checkable
class AsyncTileProvider(Protocol):
    """The contract with members of a native tile provider.

    Attributes
    ----------
    native_async
        ``True`` when the provider is served natively.
    format_type
        The configured tile format name (``format.name`` in the
        provider definition), passed back as ``format_``.
    """

    native_async: ClassVar[bool]
    format_type: str

    def get_layer(self) -> Any:
        """Get the layer metadata."""
        ...

    async def aget_tiles(
        self,
        layer: Any,
        tileset: str,
        z: int | str,
        y: int | str,
        x: int | str,
        format_: str,
    ) -> bytes | None:
        """Return the tile bytes, or None when the tile is absent within the limits."""
        ...


@runtime_checkable
class AsyncFeatureProvider(Protocol):
    """The contract with members of a native feature provider."""

    native_async: ClassVar[bool]

    async def aquery(self, **kwargs: Any) -> dict:
        """The async twin of ``query``: same keyword arguments, same GeoJSON result."""
        ...

    async def aget(self, identifier: Any, **kwargs: Any) -> dict:
        """The async twin of ``get``."""
        ...


@dataclass(frozen=True)
class MapLimits:
    """The map sizes a provider accepts.

    Attributes
    ----------
    max_width
        The largest ``width`` of a map, in pixels.
    max_height
        The largest ``height`` of a map, in pixels.
    max_pixels
        The largest ``width * height``, or None for no limit on the area.
    """

    max_width: int
    max_height: int
    max_pixels: int | None = None


class MapFormat(StrEnum):
    """The encodings of OGC API - Maps, one per conformance class.

    Each member is the value of ``f`` that asks for it.
    """

    PNG = "png"
    JPEG = "jpeg"
    JPEGXL = "jpegxl"
    TIFF = "tiff"
    SVG = "svg"
    HTML = "html"

    @property
    def media_type(self) -> str:
        """The media type of a map in this encoding."""
        match self:
            case MapFormat.PNG:
                return "image/png"
            case MapFormat.JPEG:
                return "image/jpeg"
            case MapFormat.JPEGXL:
                return "image/jxl"
            case MapFormat.TIFF:
                return "image/tiff"
            case MapFormat.SVG:
                return "image/svg+xml"
            case MapFormat.HTML:
                return "text/html"

    @property
    def conformance_class(self) -> str:
        """The URI of the conformance class of this encoding (/req/<format>/content)."""
        return f"{MAPS_CONFORMANCE_PREFIX}/{self.value}"


@dataclass(frozen=True)
class MapCapabilities:
    """The map provider's capabilities: its CRSs, its encodings and its styles.

    The provider chooses ``default_crs`` when it is built, usually the
    ``storage_crs`` of its definition when it draws in it. The route reads
    no CRS from the definition. A configuration whose ``default_crs`` is not
    among the ``crs`` is refused at startup and at every reload.

    Attributes
    ----------
    crs
        The OGC URIs of the CRSs the provider draws in, such as
        ``http://www.opengis.net/def/crs/EPSG/0/3857``, in any order
        (/req/crs/crs-definition).
    default_crs
        The CRS of a map whose request names none, one of ``crs``. The
        collection publishes it as the default of the ``crs`` parameter,
        first in its ``crs`` list, and as its ``storageCrs`` when it is not
        CRS84 (/req/collection-map/desc-crs).
    formats
        The encodings; each one declares its conformance class.
    styles
        The names of the styles the provider draws. A ``{styleId}`` that is
        not among them is answered with 404 before the map is drawn
        (/req/styled-map/map-operation).
    """

    crs: tuple[str, ...]
    default_crs: str
    formats: tuple[MapFormat, ...]
    styles: tuple[str, ...]


@dataclass(frozen=True)
class MapParameters:
    """The checked parameters of one map.

    Attributes
    ----------
    style
        The name of a configured style, from the ``{styleId}`` of
        ``/collections/{collectionId}/styles/{styleId}/map``, or None for the
        default one (/req/styled-map/map-operation).
    bbox
        ``(xmin, ymin, xmax, ymax)`` in ``crs``, within its extent;
        ``xmin > xmax`` means that the box crosses the antimeridian
        (/req/spatial-subsetting/bbox-definition).
    heights
        ``(minimum, maximum)`` of the third axis of a bbox of six numbers,
        in metres above the WGS 84 ellipsoid; None for a bbox of four
        numbers or none (/req/spatial-subsetting/bbox-definition). A
        provider that draws in two dimensions ignores them.
    width
        The width of the image in pixels, a positive integer
        (/req/scaling/width-definition).
    height
        The height of the image in pixels, a positive integer
        (/req/scaling/height-definition).
    crs
        The URI of the CRS the map is drawn in, written as the provider
        declares it (/req/crs/crs-definition).
    transparent
        Whether the background is transparent
        (/req/background/transparent-definition).
    format_
        The format to encode the map in, one the provider declares
        (/req/core/map-response).
    datetime_
        The ``datetime`` of the request, checked against the collection's
        temporal extent: an instant, or an interval with None for its open
        end, in UTC; None without ``datetime``
        (/req/datetime/datetime-definition).
    subsets
        The values asked with ``subset``, parsed by additional dimension,
        as in ``{"h": [1, 5]}``; None without ``subset``
        (/req/general-subsetting/subset-definition).
    vendor_params
        The query parameters that OGC API - Maps does not define, by name,
        as the client sent them; empty when there are none. The route does
        not check them, and the ``ETag`` of the map depends on them.
    """

    style: str | None
    bbox: tuple[float, float, float, float]
    heights: tuple[float, float] | None
    width: int
    height: int
    crs: str
    transparent: bool
    format_: str
    datetime_: datetime | TimeInterval | None
    subsets: dict[str, list[Any]] | None
    vendor_params: Mapping[str, str]


@dataclass(frozen=True)
class RenderedMap:
    """A map the provider drew.

    Attributes
    ----------
    content
        The image, encoded as ``parameters.format_`` (/req/core/map-response).
    version
        The version of the map as drawn, the value ``aget_version`` returns
        for the same parameters when nothing changes in between; the route
        builds the ``ETag`` from it.
        None when the version is unknown, and the map goes without cache
        headers.
    extra_headers
        Response headers of the provider's own, empty by default. The route
        sends them unless it sets a header of the same name, or the header
        describes the image or its caching (``Content-Type``,
        ``Cache-Control``, ``ETag``, ``Vary`` and the like): those are
        dropped, with a warning in the log.
    """

    content: bytes
    version: str | None
    extra_headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NotRenderedMap:
    """A map the provider did not draw because the server is busy for now.

    The provider returns this value for a condition that clears by itself:
    a full render queue, or a render that ran out of time. The same request
    may succeed later, so the route answers with ``status`` and logs no
    traceback.

    A fault of the engine is raised as an exception instead, as pygeoapi's
    providers do, and the route answers 500 and logs its traceback.

    Attributes
    ----------
    status
        The status of the answer: 503 for a full queue, 504 for a render
        that ran out of time.
    message
        What the client reads in the error.
    retry_after
        Seconds before the client should try again, sent as ``Retry-After``;
        None to send no header.
    """

    status: HTTPStatus
    message: str
    retry_after: int | None


@runtime_checkable
class AsyncMapProvider(Protocol):
    """The contract with members of a native map provider.

    A class that sets ``native_async`` must define all of them; a
    configuration that names a class missing one is refused at start-up,
    and the error says which.

    Attributes
    ----------
    native_async
        ``True`` when the provider is served natively.
    """

    native_async: ClassVar[bool]

    @property
    def limits(self) -> MapLimits:
        """The largest limits of a drawn map."""
        ...

    @property
    def capabilities(self) -> MapCapabilities:
        """The CRSs, the encodings and the styles used to draw the maps."""
        ...

    async def arender_map(self, parameters: MapParameters) -> RenderedMap | NotRenderedMap:
        """Draw the map, or tell why the server cannot draw it now.

        The map covers exactly ``parameters.bbox`` in ``parameters.crs``:
        the route declares both in ``Content-Bbox`` and ``Content-Crs``.
        ``parameters.style`` is None or one of ``capabilities.styles``.

        Parameters
        ----------
        parameters
            The checked parameters of the map.

        Returns
        -------
        RenderedMap or NotRenderedMap
            The encoded image and the version it was drawn from, or the
            reason the server cannot draw it now.

        Raises
        ------
        ProviderGenericError
            When the engine fails; the route answers 500 and logs the
            traceback.
        """
        ...

    async def aget_version(self, parameters: MapParameters) -> str | None:
        """Get the version of the map these parameters would draw, without drawing it.

        A version combines every property of the request and of the provider
        that makes the map reproducible: the data, the definition, the style
        and the engine. The HTTP cache compares it with the client's to
        decide between drawing the map and answering 304, so it must be
        cheap: it reads metadata and never the data. A map served under a
        version must be drawn from the data that version names, so a
        provider that cannot pin its reads to one version returns None.

        Parameters
        ----------
        parameters
            The checked parameters of the map, as ``arender_map`` gets them.

        Returns
        -------
        str or None
            The version, or None when the version of the data is unknown.
        """
        ...

    def close(self) -> None:
        """Clean up the resources the provider owns.

        It is safe to call from any thread, returns without waiting for the
        maps in progress, and does nothing when called again.
        """
        ...


@runtime_checkable
class VersionedProvider(Protocol):
    """A contract that tells which version of the response a request would get.

    The ``ETag`` of a response is built from that version; a provider
    without ``aget_version`` gets no cache headers.
    """

    async def aget_version(self, *args: Any, **kwargs: Any) -> str | None:
        """Get the version of the answer to these arguments, without computing it.

        It changes whenever the answer can change, and it reads metadata
        only. Neither the tiles nor the data a map is drawn from.

        Parameters
        ----------
        *args
            The positional arguments of the provider's data method: the
            ``MapParameters`` of ``arender_map`` for a map provider.
        **kwargs
            The keyword arguments of the provider's data method: those of
            ``aget_tiles`` for a tile provider.

        Returns
        -------
        str or None
            The version, or None when it is unknown.
        """
        ...


class EdrFormat(StrEnum):
    """The encodings of an EDR data response.

    Each member is the value of ``f`` that asks for it.
    """

    COVERAGEJSON = "CoverageJSON"

    @property
    def media_type(self) -> str:
        """The media type of a response in this encoding."""
        return "application/prs.coverage+json"

    @property
    def conformance_classes(self) -> tuple[str, str]:
        """The URIs of the conformance class of this encoding, in EDR 1.0 and in EDR 1.1."""
        first, second = (f"{prefix}/covjson" for prefix in EDR_CONFORMANCE_PREFIXES)
        return first, second


@dataclass(frozen=True)
class EdrParameter:
    """A parameter a collection offers, such as a temperature.

    Attributes
    ----------
    name
        The identifier clients put in ``parameter-name``.
    label
        The name a person reads.
    unit
        The unit of the values, as a symbol.
    description
        What the parameter measures; None when there is nothing to add.
    standard_name
        The CF standard name; None when the parameter has none.
    """

    name: str
    label: str
    unit: str
    description: str | None = None
    standard_name: str | None = None


@dataclass(frozen=True)
class EdrLimits:
    """The provider's limit on the size of an answer.

    Attributes
    ----------
    max_values
        The most values one query may return, counted over parameters,
        times and places; None when the provider sets no limit and only the
        server's applies.
    """

    max_values: int | None


@dataclass(frozen=True)
class EdrCapabilities:
    """What an EDR provider offers: query types, CRSs, encodings and parameters.

    Attributes
    ----------
    query_types
        The queries the collection answers: ``position``, ``area`` or both.
    crs
        The CRSs a query may name, as OGC URIs. CRS84 must be among them.
    default_crs
        The CRS of a query that names none; one of ``crs``.
    formats
        The encodings the collection answers in.
    parameters
        The parameters the collection offers.
    """

    query_types: tuple[str, ...]
    crs: tuple[str, ...]
    default_crs: str
    formats: tuple[EdrFormat, ...]
    parameters: tuple[EdrParameter, ...]


@dataclass(frozen=True)
class PositionQuery:
    """The checked parameters of a position query.

    Attributes
    ----------
    coords
        The point or points to sample, in ``crs``.
    parameter_names
        The parameters asked for; every one is in ``capabilities.parameters``.
    datetime_
        The instant or interval asked for; None for the whole time axis.
    crs
        One of ``capabilities.crs``.
    format_
        One of ``capabilities.formats``.
    max_values
        The limit the route applies, the smaller of the provider's and the
        server's. The provider counts against it and returns ``DataTooLarge``
        when the query exceeds it.
    vendor_params
        The query parameters the standard does not define, as received.
    """

    coords: Point | MultiPoint
    parameter_names: tuple[str, ...]
    datetime_: datetime | TimeInterval | None
    crs: str
    format_: str
    max_values: int
    vendor_params: Mapping[str, str]


@dataclass(frozen=True)
class AreaQuery:
    """The checked parameters of an area query.

    Attributes
    ----------
    coords
        The polygon or polygons to sample, in ``crs``.
    parameter_names
        The parameters asked for; every one is in ``capabilities.parameters``.
    datetime_
        The instant or interval asked for; None for the whole time axis.
    crs
        One of ``capabilities.crs``.
    format_
        One of ``capabilities.formats``.
    max_values
        The limit the route applies, the smaller of the provider's and the
        server's. The provider counts against it and returns ``DataTooLarge``
        when the query exceeds it.
    vendor_params
        The query parameters the standard does not define, as received.
    resolution_x
        The number of samples along x; None to use the grid's own.
    resolution_y
        The number of samples along y; None to use the grid's own.
    """

    coords: Polygon | MultiPolygon
    parameter_names: tuple[str, ...]
    datetime_: datetime | TimeInterval | None
    crs: str
    format_: str
    max_values: int
    vendor_params: Mapping[str, str]
    resolution_x: int | None
    resolution_y: int | None


EdrQuery = PositionQuery | AreaQuery


@dataclass(frozen=True)
class RetrievedData:
    """The data the provider read.

    Attributes
    ----------
    content
        The response body, encoded as ``query.format_``.
    version
        The version of the data as read, the value ``aget_version`` returns
        for the same query when nothing changes in between; the route builds
        the ``ETag`` from it. None when the version is unknown, and the
        response goes without cache headers.
    extra_headers
        Response headers of the provider's own, empty by default. The route
        sends them unless it sets a header of the same name, or the header
        describes the body or its caching: those are dropped, with a warning
        in the log.
    """

    content: bytes
    version: str | None
    extra_headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NoDataFound:
    """The query matched no value: the place or the time lies outside the data.

    The route answers 204.
    """


@dataclass(frozen=True)
class NotRetrievedData:
    """Data the provider did not read because the server is busy for now.

    The provider returns this value for a condition that clears by itself,
    so the route answers with ``status`` and logs no traceback. A fault of
    the store is raised as an exception instead, and the route answers 500.

    Attributes
    ----------
    status
        The status of the answer: 503 for a busy store, 504 for a read that
        ran out of time.
    message
        What the client reads in the error.
    retry_after
        Seconds before the client should try again, sent as ``Retry-After``;
        None to send no header.
    """

    status: HTTPStatus
    message: str
    retry_after: int | None


@dataclass(frozen=True)
class DataTooLarge:
    """A query that would return more values than ``query.max_values``.

    The route answers 413.

    Attributes
    ----------
    values
        The number of values the query would return.
    limit
        The limit it exceeds.
    """

    values: int
    limit: int


@runtime_checkable
class AsyncEdrProvider(Protocol):
    """The contract with members of a native EDR provider.

    A class that sets ``native_async`` must define all of them; a
    configuration that names a class missing one is refused at start-up,
    and the error says which.

    Attributes
    ----------
    native_async
        ``True`` when the provider is served natively.
    """

    native_async: ClassVar[bool]

    @property
    def limits(self) -> EdrLimits:
        """The largest answer a query may return."""
        ...

    @property
    def capabilities(self) -> EdrCapabilities:
        """The query types, CRSs, encodings and parameters of the collection."""
        ...

    async def aretrieve_data(
        self, query: EdrQuery
    ) -> RetrievedData | NoDataFound | NotRetrievedData | DataTooLarge:
        """Read the data a query asks for, or tell why the route cannot answer.

        ``query.parameter_names``, ``query.crs`` and ``query.format_`` come
        from ``capabilities``, and ``query.max_values`` is the limit to
        count against.

        Parameters
        ----------
        query
            The checked parameters of the query.

        Returns
        -------
        RetrievedData or NoDataFound or NotRetrievedData or DataTooLarge
            The encoded data and its version (200); no value (204); the
            reason the server is busy (503 or 504); or the size of a query
            over the limit (413).

        Raises
        ------
        ProviderGenericError
            When the store fails; the route answers 500 and logs the
            traceback.
        """
        ...

    async def aget_version(self, query: EdrQuery) -> str | None:
        """Get the version of the data this query would read, without reading it.

        The HTTP cache compares it with the client's to decide between
        reading the data and answering 304, so it must be cheap: it reads
        metadata and never the values. A provider that cannot pin its reads
        to one version returns None.

        Parameters
        ----------
        query
            The checked parameters of the query, as ``aretrieve_data`` gets
            them.

        Returns
        -------
        str or None
            The version, or None when the version of the data is unknown.
        """
        ...

    def close(self) -> None:
        """Clean up the resources the provider owns.

        It is safe to call from any thread, returns without waiting for the
        queries in progress, and does nothing when called again.
        """
        ...
