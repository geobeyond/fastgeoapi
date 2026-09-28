"""The pieces a map is drawn from: a source, its styles, a renderer.

A source says where the collection's data is and what it holds. The
styles turn it into documents in the renderer's own style language. A
renderer gets a resolved request, with its style, extent and size, and
returns PNG bytes. None of them knows about collections, CRS negotiation
or HTTP: those stay in the provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MapRequest:
    """One map to draw: an EPSG:3857 extent in metres, a size, a style."""

    bbox: tuple[float, float, float, float]
    width: int
    height: int
    # The style document, in the renderer's own language. Out of the repr:
    # it carries the signed URL of the data.
    style: Any = field(compare=False, hash=False, repr=False)
    transparent: bool = True

    def __post_init__(self) -> None:
        """Refuse an empty extent or an empty image."""
        xmin, ymin, xmax, ymax = self.bbox
        if not (xmin < xmax and ymin < ymax):
            raise ValueError(f"invalid bbox {self.bbox}: minimums must be below maximums")
        if self.width < 1 or self.height < 1:
            raise ValueError("width and height must be positive")


@dataclass(frozen=True, slots=True)
class SourceContent:
    """What a source holds, for a style that does not declare it."""

    kind: str
    """``"vector"`` or ``"raster"``, as MapLibre names its source types."""
    layers: tuple[str, ...] = ()
    """The data layers of a vector source, for a default style that draws all of them."""
    tile_size: int | None = None
    """The width in pixels of one tile of a raster source, when known."""
    encoding: str | None = None
    """How the tiles are encoded, when the data says so: ``"mvt"``, ``"png"``, ``"avif"``."""


@runtime_checkable
class MapSource(Protocol):
    """A collection's data, as a renderer outside this process reads it.

    Every source is read this way today: the renderer fetches the data at
    the source's URL. Two other ways are possible and not written yet: the
    data put inline in the style, such as the GeoJSON of a features
    collection, and the data read in this process and handed to the
    renderer, such as the windows of a raster.
    """

    format: str
    """The format of the data, which tells a style how to point at it: ``"pmtiles"``."""

    def url(self) -> str:
        """Where to read the data now: a file URL, a public URL or a presigned one."""
        ...

    def content(self) -> SourceContent:
        """What the data holds: vector layers, or raster tiles and their size."""
        ...


@runtime_checkable
class MapStyles(Protocol):
    """The styles of one map collection."""

    def names(self) -> list[str]:
        """The configured style names."""
        ...

    def style(self, name: str | None, transparent: bool) -> Any:
        """The style ``name``, or the default one, pointed at the source.

        ``transparent`` drops the background. A name that is not
        configured raises :class:`KeyError`.
        """
        ...


class RenderError(RuntimeError):
    """The renderer could not produce an image."""


class SourceNotDrawableError(ValueError):
    """The styles cannot point the renderer at this source; raised before any render."""


@runtime_checkable
class MapRenderer(Protocol):
    """An asynchronous drawing backend."""

    async def render(self, request: MapRequest) -> bytes:
        """The PNG bytes of ``request``.

        Any exception counts as a broken renderer: the provider replaces it
        and answers the map with a generic error.
        """
        ...

    async def aclose(self) -> None:
        """Release the processes and memory the renderer holds."""
        ...
