"""A real Mapbox Vector Tile, written by hand, for the renderer tests.

One layer, ``land``, with one polygon that covers the tile and its buffer.
In an archive holding only tile 0/0/0, MapLibre overzooms it at every zoom,
so any map of the archive is filled with the layer.
"""

from __future__ import annotations

import gzip
from pathlib import Path

from tests.pmtiles_fixtures import write_archive

EXTENT = 4096


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte, value = value & 0x7F, value >> 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 31)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def _uint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def land_tile() -> bytes:
    """An uncompressed MVT whose ``land`` polygon covers the whole tile."""
    edge, span = -64, EXTENT + 128
    commands = [1 | 1 << 3, _zigzag(edge), _zigzag(edge)]  # MoveTo
    commands += [2 | 3 << 3, _zigzag(span), 0, 0, _zigzag(span), _zigzag(-span), 0]  # LineTo x3
    commands += [7 | 1 << 3]  # ClosePath
    geometry = b"".join(_varint(c) for c in commands)
    feature = _uint(1, 1) + _uint(3, 3) + _field(4, geometry)  # id, POLYGON, geometry
    layer = _uint(15, 2) + _field(1, b"land") + _field(2, feature) + _uint(5, EXTENT)
    return _field(3, layer)


def land_archive(path: Path) -> Path:
    """A PMTiles archive with the land tile at 0/0/0 and its ``land`` vector layer."""
    return write_archive(
        path,
        {(0, 0, 0): gzip.compress(land_tile())},
        metadata={"name": "land", "vector_layers": [{"id": "land"}]},
    )
