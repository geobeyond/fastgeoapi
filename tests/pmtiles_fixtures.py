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
    tile_type: TileType = TileType.MVT,
) -> Path:
    """Write `tiles` (already compressed as declared) into a PMTiles archive at `path`."""
    zooms = sorted({z for z, _, _ in tiles})
    header = {
        "tile_type": tile_type,
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


def raster_tile(
    size: int = 256, colour: tuple[int, int, int] = (200, 30, 30), kind: str = "PNG"
) -> bytes:
    """One square raster tile of a single colour, encoded as `kind` (PNG, JPEG, WEBP, AVIF)."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (size, size), colour).save(buffer, format=kind)
    return buffer.getvalue()


def raster_archive(
    path: Path, *, size: int = 256, kind: str = "PNG", gzipped: bool = False
) -> Path:
    """A raster PMTiles archive with one tile, z0, the whole world in one colour."""
    tile = raster_tile(size, kind=kind)
    return write_archive(
        path,
        {(0, 0, 0): gzip.compress(tile) if gzipped else tile},
        metadata={"name": path.stem},
        tile_compression=Compression.GZIP if gzipped else Compression.NONE,
        tile_type=TileType[kind],
    )


def terrarium_tile(z: int, x: int, y: int, size: int = 256) -> bytes:
    """A PNG tile of a steep cone in the middle of the world, in the Terrarium encoding.

    The cone is 30 km high with a base an eighth of the world wide: steep
    enough for MapLibre's hillshade to shade it at the zooms the archive
    holds. Terrarium stores ``height + 32768`` metres as R * 256 + G + B / 256.
    """
    import io
    import math

    from PIL import Image

    pixels = []
    for row in range(size):
        for col in range(size):
            # Where the pixel sits in Web Mercator, the world from 0 to 1 on both axes.
            u = (x + (col + 0.5) / size) / 2**z
            v = (y + (row + 0.5) / size) / 2**z
            height = max(0.0, 30_000.0 * (1 - math.hypot(u - 0.5, v - 0.5) / 0.06))
            value = height + 32768
            pixels.append((int(value // 256), int(value % 256), int(value % 1 * 256)))
    image = Image.new("RGB", (size, size))
    image.putdata(pixels)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def terrarium_archive(path: Path, *, max_zoom: int = 1) -> Path:
    """A Terrarium elevation archive from zoom 0 to ``max_zoom``: one cone, flat land around it."""
    tiles = {
        (z, x, y): terrarium_tile(z, x, y)
        for z in range(max_zoom + 1)
        for x in range(2**z)
        for y in range(2**z)
    }
    return write_archive(
        path,
        tiles,
        metadata={"name": path.stem},
        tile_compression=Compression.NONE,
        tile_type=TileType.PNG,
    )
