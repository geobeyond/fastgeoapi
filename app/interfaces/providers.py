"""The Protocols of fastgeoapi's providers which serve natively, one per family.

A provider class takes the native path by setting ``native_async = True``;
any other provider is served by pygeoapi. A class matches a Protocol by
its members, whether or not it inherits from fastgeoapi's mixin.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, ClassVar, Protocol, runtime_checkable

MAPS_CONFORMANCE_PREFIX = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf"
"""The start of the URI of every OGC API - Maps conformance class."""


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
    """The map provider's capabilities as defined by CRSs and the formats of the map.

    Attributes
    ----------
    crs
        The OGC URIs of the CRSs, such as
        ``http://www.opengis.net/def/crs/EPSG/0/3857``, in the provider's
        order of preference: the first is the default when the collection's
        ``storage_crs`` is not among them (/req/crs/crs-definition).
    formats
        The encodings; each one declares its conformance class.
    """

    crs: tuple[str, ...]
    formats: tuple[MapFormat, ...]


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
        temporal extent, or None (/req/datetime/datetime-definition).
    subsets
        The values asked with ``subset``, by additional dimension, or None
        (/req/general-subsetting/subset-definition).
    """

    style: str | None
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    crs: str
    transparent: bool
    format_: str
    datetime_: str | None
    subsets: dict[str, list[Any]] | None


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
        """The CRSs and the encodings used to draw the maps."""
        ...

    async def arender_map(self, parameters: MapParameters) -> bytes:
        """Draw the map and return the image, encoded as ``parameters.format_``.

        Parameters
        ----------
        parameters
            The checked parameters of the map.

        Returns
        -------
        bytes
            The encoded image.

        Raises
        ------
        ProviderItemNotFoundError
            For a ``style`` the provider does not know; the route answers 404.
        ProviderGenericError
            When the engine fails; the route answers 500.
        """
        ...

    async def aget_version(self, parameters: MapParameters) -> str | None:
        """Get the version of the map that would be drawn, without drawing it.

        The version changes whenever the image for these parameters can
        change: the data, the definition, the style or the engine. It reads
        metadata only. A map served under a version must be drawn from the
        data that version names, so a provider that cannot pin its reads to
        one version returns None.

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
        """Release the engine once the maps, which are drawn, are done.

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
