"""PMTiles archives for the tests, written by the library's own Writer.

Payloads are recognisable (`tile z/x/y`, gzip) so a test can tell which
tile it got back. `leafy_archive` writes enough tiles for the writer to
spill entries into leaf directories, which is where the lookup logic
earns its keep: at 20,000 tiles the root shrinks to 49 bytes and the
leaves hold 44 KB; at 6,000 everything still fits in the root.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

WORLD_E7 = {
    "min_lon_e7": -1800000000,
    "min_lat_e7": -850511287,
    "max_lon_e7": 1800000000,
    "max_lat_e7": 850511287,
}


def TILE_BYTES(z: int, x: int, y: int) -> bytes:
    """The gzip payload `tile z/x/y`."""
    return gzip.compress(f"tile {z}/{x}/{y}".encode())


def write_archive(
    path: Path,
    tiles: dict[tuple[int, int, int], bytes],
    *,
    metadata: dict | None = None,
    tile_compression: Compression = Compression.GZIP,
) -> Path:
    """Write `tiles` (already compressed as declared) into a PMTiles archive at `path`."""
    zooms = sorted({z for z, _, _ in tiles})
    header = {
        "tile_type": TileType.MVT,
        "tile_compression": tile_compression,
        **WORLD_E7,
        "center_zoom": zooms[0],
        "center_lon_e7": 0,
        "center_lat_e7": 0,
    }
    if metadata is None:
        metadata = {
            "name": path.stem,
            "vector_layers": [{"id": "layer", "minzoom": zooms[0], "maxzoom": zooms[-1]}],
        }
    with path.open("wb") as handle:
        writer = Writer(handle)
        for (z, x, y), data in tiles.items():
            writer.write_tile(zxy_to_tileid(z, x, y), data)
        writer.finalize(header, metadata)
    return path


def leafy_archive(path: Path, *, z: int = 8, count: int = 20_000) -> Path:
    """An archive whose directory does not fit in the root: leaves appear."""
    side = 2**z
    tiles = {}
    for i in range(count):
        x, y = i % side, (i // side) % side
        tiles[z, x, y] = TILE_BYTES(z, x, y)
    return write_archive(path, tiles)
