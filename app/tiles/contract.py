"""The contract between the tile provider and the backends that read tiles.

A tile source reads the tiles of one collection's data, wherever and in
whatever container they are stored, and says what they are. The tile
provider answers pygeoapi from what the source says and from its own
configuration: the kind of tiles decides the media type, the tileset
metadata and the TileJSON, so a new backend is a source and its
registration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

VECTOR_MEDIA_TYPES = ("application/vnd.mapbox-vector-tile", "application/x-protobuf")
"""The media types of vector tiles; the first is the one to configure."""

FORMAT_PARAMETERS = {
    "application/vnd.mapbox-vector-tile": "mvt",
    "application/x-protobuf": "mvt",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/avif": "avif",
}
"""The ``f`` value of the tile links for each media type a tile provider serves."""


def format_parameter(media_type: str | None) -> str:
    """The ``f`` value of the links to tiles served as ``media_type``; ``mvt`` when unknown."""
    return FORMAT_PARAMETERS.get(media_type or "", "mvt")


def data_type_for(media_type: str | None, dem: str | None) -> str:
    """The OGC ``dataType`` of tiles served as ``media_type``: ``vector``, ``map`` or ``coverage``.

    Decided from the configuration alone, so that describing a tileset
    reads no data.
    """
    if dem is not None:
        return "coverage"
    if media_type is not None and media_type.startswith("image/"):
        return "map"
    return "vector"


class TileSourceError(Exception):
    """The data cannot be served as the provider is configured; the message says what to change."""


class TileOutsideError(LookupError):
    """The tile lies outside the zooms the data holds."""


@dataclass(frozen=True, slots=True)
class VectorLayer:
    """One layer of vector tiles, as TileJSON lists it."""

    id: str
    description: str | None = None
    minzoom: int | None = None
    maxzoom: int | None = None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TileContent:
    """What a tile source holds, as the tileset metadata and the TileJSON describe it."""

    data_type: str
    """``"vector"``, ``"map"`` or ``"coverage"``, the OGC names."""
    media_type: str
    """The media type the tiles go out as."""
    format_parameter: str
    """The ``f`` value of the links to the tiles."""
    min_zoom: int
    max_zoom: int
    bounds: tuple[float, float, float, float]
    """West, south, east and north, in degrees."""
    center: tuple[float, float, int]
    """Longitude and latitude in degrees, and a zoom."""
    name: str | None = None
    description: str | None = None
    attribution: str | None = None
    layers: tuple[VectorLayer, ...] = ()
    """The layers of vector tiles."""
    tile_size: int | None = None
    """The width in pixels of raster tiles, when known."""
    dem: str | None = None
    """How coverage tiles encode elevations: ``"terrarium"`` or ``"mapbox"``."""


@runtime_checkable
class TileSource(Protocol):
    """The tiles of one collection's data, read wherever they are stored.

    Every call has a synchronous face, for pygeoapi's own chain, and an
    awaited one, for the native route. ``tile`` returns None for a tile
    the data does not hold within its zooms, and raises
    :class:`TileOutsideError` outside them and :class:`TileSourceError`
    when the data cannot be served as configured.
    """

    format: str
    """The container the tiles come in: ``"pmtiles"``."""

    def content(self) -> TileContent:
        """What the data holds."""
        ...

    async def acontent(self) -> TileContent:
        """Async twin of :meth:`content`."""
        ...

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        """The bytes of one tile, decompressed."""
        ...

    async def atile(self, z: int, x: int, y: int) -> bytes | None:
        """Async twin of :meth:`tile`."""
        ...
