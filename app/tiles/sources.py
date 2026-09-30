"""The backends that read tiles, by the data they recognise.

Each backend registers its source here, with a check that recognises
its data and a builder. The generic tile provider asks the registry, so
a new container adds a source and its registration without touching the
provider.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from app.provider.storage import ByteRanges, CachedRanges
from app.tiles.contract import TileSource


@dataclass(frozen=True, slots=True)
class TileSourceContext:
    """What a source gets from its tile provider to reach the collection's data.

    The callables are lazy: a source calls them at its first read, so the
    provider is built without I/O, and a test can replace the provider's
    reads after building it.
    """

    data: str
    """The provider's ``data``: a path, a URL or a bucket key."""
    options: Mapping[str, Any]
    """The provider's options."""
    media_type: str | None
    """The configured ``format.mimetype``, the one the tile routes answer with."""
    dem: str | None
    """The configured elevation encoding."""
    ranges: Callable[[], ByteRanges]
    """Returns ranged reads of the data object, one fetch for identical reads in flight."""
    cached: Callable[[], CachedRanges | None]
    """Returns the range cache of a remote object, or None."""
    offload: Callable[..., Awaitable[Any]]
    """Runs a blocking call in a worker thread: ``await offload(fn, *args)``."""


@dataclass(frozen=True, slots=True)
class TileSourceFormat:
    """One registered backend: how to recognise its data and build its source."""

    format: str
    matches: Callable[[str], bool]
    build: Callable[[TileSourceContext], TileSource]


_REGISTRY: dict[str, TileSourceFormat] = {}


def register_tile_source(
    format: str,
    *,
    matches: Callable[[str], bool],
    build: Callable[[TileSourceContext], TileSource],
) -> None:
    """Register the source of ``format``; ``matches`` recognises its data."""
    _REGISTRY[format] = TileSourceFormat(format, matches, build)


def tile_source_for(data: str) -> TileSourceFormat:
    """The registered backend that reads ``data``; raises :class:`LookupError` otherwise."""
    for registered in _REGISTRY.values():
        if registered.matches(data):
            return registered
    raise LookupError(f"no tile source reads {data}")


def _is_pmtiles(data: str) -> bool:
    return PurePosixPath(urlsplit(data).path).suffix.lower() == ".pmtiles"


def _pmtiles(context: TileSourceContext) -> TileSource:
    # Imported here: the PMTiles reader needs the optional pmtiles extra.
    from app.provider.pmtiles import PMTilesTiles  # ty: ignore[unresolved-import]

    return PMTilesTiles(context)


register_tile_source("pmtiles", matches=_is_pmtiles, build=_pmtiles)
