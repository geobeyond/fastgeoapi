"""Where a map renderer reads a collection's data.

The renderer runs in its own process and reads the data itself, by URL:
a file URL for a local object, the public URL for a public one, and a
presigned URL for a private bucket. A presigned URL is renewed between
renders once a fifth of its life is left, so that no signature runs out
halfway through a map.

Each data format registers its source here, with a check that recognises
its data and a builder. The map provider asks the registry, so a new
format adds a source and its registration without touching the provider.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.maps.contract import MapSource, SourceContent, SourceNotDrawableError


class ObjectUrl:
    """The URL of one data object, for a reader outside this process."""

    def __init__(
        self,
        *,
        local_path: Path | None = None,
        public_url: str | None = None,
        signer: Callable[[timedelta], str] | None = None,
        resolver: Callable[[], str] | None = None,
        ttl: timedelta = timedelta(hours=1),
        renew_at: float = 0.2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Give exactly one of a local path, a public URL, a signer or a resolver.

        A resolver is asked at every use, for a URL that can change: one that
        names a version of the object, for instance.
        """
        given = (local_path, public_url, signer, resolver)
        if sum(value is not None for value in given) != 1:
            raise ValueError("give exactly one of local_path, public_url, signer or resolver")
        self._local_path = local_path
        self._public_url = public_url
        self._signer = signer
        self._resolver = resolver
        self._ttl = ttl
        self._renew_at = renew_at
        self._clock = clock
        self._signed: str | None = None
        self._renew_after = 0.0

    def current(self) -> str:
        """The URL to read the object at now, signed again when needed."""
        if self._resolver is not None:
            return self._resolver()
        if self._local_path is not None:
            return f"file://{self._local_path.resolve()}"
        if self._public_url is not None:
            return self._public_url
        if self._signer is None:
            raise RuntimeError("an ObjectUrl without a path or URL needs a signer")
        now = self._clock()
        if self._signed is None or now >= self._renew_after:
            self._signed = self._signer(self._ttl)
            self._renew_after = now + self._ttl.total_seconds() * (1 - self._renew_at)
        return self._signed


class PMTilesSource:
    """A PMTiles archive read in place: vector tiles, or raster tiles in PNG, JPEG, WebP or AVIF."""

    format = "pmtiles"

    def __init__(
        self,
        location: ObjectUrl,
        read: Callable[[int, int], bytes],
        *,
        tile_size: int | None = None,
        dem: str | None = None,
    ) -> None:
        """``read(offset, length)`` returns a byte range of the archive.

        The header is read through it the first time :meth:`content` is
        called, then the metadata of a vector archive, or the first tile of
        a raster one when ``tile_size`` is not given, to measure it. With
        ``dem``, the raster tiles are elevations in that encoding.
        """
        self._location = location
        self._read = read
        self._tile_size = tile_size
        self._dem = dem
        self._content: SourceContent | None = None

    def url(self) -> str:
        """The URL of the archive."""
        return self._location.current()

    def content(self) -> SourceContent:
        """What the archive holds, as the tile type in its header says."""
        if self._content is None:
            self._content = self._read_content()
        return self._content

    def _read_content(self) -> SourceContent:
        try:
            from pmtiles.reader import Reader
            from pmtiles.tile import TileType
        except ImportError as error:
            raise ImportError("reading a PMTiles archive needs the pmtiles extra") from error
        # Here, not at the top: the tile types come from the optional pmtiles extra.
        from app.provider.pmtiles_types import tiles_problem

        reader = Reader(self._read)
        tile_type = reader.header()["tile_type"]
        if self._dem is not None:
            problem = tiles_problem(tile_type, media_type=None, dem=self._dem)
            if problem is not None:
                raise SourceNotDrawableError(problem)
        encoding = None if tile_type == TileType.UNKNOWN else tile_type.name.lower()
        if tile_type in (TileType.PNG, TileType.JPEG, TileType.WEBP, TileType.AVIF):
            size = self._tile_size or self._first_tile_width()
            kind = "raster-dem" if self._dem is not None else "raster"
            return SourceContent(kind, tile_size=size, encoding=encoding, dem=self._dem)
        metadata = reader.metadata()
        layers = tuple(layer["id"] for layer in metadata.get("vector_layers", []))
        return SourceContent("vector", layers=layers, encoding=encoding)

    def _first_tile_width(self) -> int | None:
        """The width of the archive's first tile, or None when it cannot be read.

        Neither the PMTiles header nor TileJSON carries the tile size, and
        MapLibre draws a raster source at the size it is told, 512 by default.
        """
        import gzip
        import io

        from pmtiles.reader import all_tiles
        from pmtiles.tile import Compression, deserialize_header

        try:
            from PIL import Image
        except ImportError:
            return None
        compression = deserialize_header(self._read(0, 127))["tile_compression"]
        for _, data in all_tiles(self._read):
            if compression == Compression.GZIP:
                data = gzip.decompress(data)
            try:
                return Image.open(io.BytesIO(data)).width
            except (OSError, ValueError):
                return None
        return None


@dataclass(frozen=True, slots=True)
class SourceContext:
    """What a source gets from its map provider to reach the collection's data.

    Both callables are lazy: a source calls only the one it needs, when it
    needs it.
    """

    data: str
    """The provider's ``data``: a path, a URL or a bucket key."""
    options: Mapping[str, Any]
    """The provider's options."""
    location: Callable[[], ObjectUrl]
    """Returns the URL of the data object, for a reader outside this process."""
    ranges: Callable[[], Callable[[int, int], bytes]]
    """Returns a reader of byte ranges of the data object, ``read(offset, length)``."""


@dataclass(frozen=True, slots=True)
class SourceFormat:
    """One registered data format: how to recognise its data and build its source."""

    format: str
    matches: Callable[[str], bool]
    build: Callable[[SourceContext], MapSource]


_REGISTRY: dict[str, SourceFormat] = {}


def register_source(
    format: str,
    *,
    matches: Callable[[str], bool],
    build: Callable[[SourceContext], MapSource],
) -> None:
    """Register the source of ``format``; ``matches`` recognises its data."""
    _REGISTRY[format] = SourceFormat(format, matches, build)


def source_for(data: str) -> SourceFormat:
    """The registered format that reads ``data``; raises :class:`LookupError` otherwise."""
    for registered in _REGISTRY.values():
        if registered.matches(data):
            return registered
    raise LookupError(f"no map source reads {data}")


def _is_pmtiles(data: str) -> bool:
    return Path(urlsplit(data).path).suffix.lower() == ".pmtiles"


register_source(
    "pmtiles",
    matches=_is_pmtiles,
    build=lambda context: PMTilesSource(
        context.location(),
        context.ranges(),
        tile_size=context.options.get("tile_size"),
        dem=context.options.get("dem"),
    ),
)
