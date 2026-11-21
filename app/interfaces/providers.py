"""Fastgeoapi's provider protocols, one per family.

A provider class takes the native path by setting ``native_async = True``;
any other provider is served by pygeoapi. A class matches a Protocol by
its members, whether or not it inherits from fastgeoapi's mixin.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from http import HTTPStatus
from typing import Any, ClassVar, Protocol, runtime_checkable

from app.interfaces.ogc import MAPS_CONFORMANCE_PREFIX
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

    Attributes
    ----------
    crs
        The OGC URIs of the CRSs, such as
        ``http://www.opengis.net/def/crs/EPSG/0/3857``, in the provider's
        order of preference: the first is the default when the collection's
        ``storage_crs`` is not among them (/req/crs/crs-definition).
    formats
        The encodings; each one declares its conformance class.
    styles
        The names of the styles the provider draws. A ``{styleId}`` that is
        not among them is answered with 404 before the map is drawn
        (/req/styled-map/map-operation).
    """

    crs: tuple[str, ...]
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
    """

    style: str | None
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    crs: str
    transparent: bool
    format_: str
    datetime_: datetime | TimeInterval | None
    subsets: dict[str, list[Any]] | None


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
    """

    content: bytes
    version: str | None


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
