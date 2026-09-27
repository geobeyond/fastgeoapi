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


@runtime_checkable
class MapSource(Protocol):
    """A collection's data, as a renderer outside this process reads it."""

    format: str
    """The format of the data, which tells a style how to point at it: ``"pmtiles"``."""

    def url(self) -> str:
        """Where to read the data now: a file URL, a public URL or a presigned one."""
        ...

    def layers(self) -> list[str]:
        """The names of the data layers, for a default style that draws all of them."""
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
