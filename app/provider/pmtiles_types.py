"""What the tiles of a PMTiles archive are, and how they are served and drawn.

The archive's header names the tile type; a tile provider's definition
names the media type the routes answer with. The PMTiles tile source and
the PMTiles map source ask here which types can be served, under which
media types, whether an elevation encoding fits the tiles, and how wide
a tile is. The width is read from the image's own header bytes, because
Pillow is not a dependency of the server.
"""

from __future__ import annotations

import struct

from pmtiles.tile import TileType

from app.tiles.contract import VECTOR_MEDIA_TYPES, format_parameter

MEDIA_TYPES: dict[TileType, tuple[str, ...]] = {
    TileType.MVT: VECTOR_MEDIA_TYPES,
    TileType.PNG: ("image/png",),
    TileType.JPEG: ("image/jpeg",),
    TileType.WEBP: ("image/webp",),
    TileType.AVIF: ("image/avif",),
}
"""The media types each servable tile type goes out as; the first is the one to configure."""

LOSSLESS = (TileType.PNG, TileType.WEBP)
"""Tile types that keep an elevation exact and that MapLibre Native decodes."""

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def tiles_problem(tile_type: TileType, *, media_type: str | None, dem: str | None) -> str | None:
    """Why tiles of ``tile_type`` cannot be served or drawn as configured; None when they can.

    ``media_type`` is the configured one, None where no route answers
    with it (a map); ``dem`` is the configured elevation encoding.
    """
    served = MEDIA_TYPES.get(tile_type)
    if served is None:
        return f"PMTiles tiles of type {tile_type.name} are not supported"
    if media_type is not None and media_type not in served:
        return (
            f"the archive holds {tile_type.name} tiles: set format to "
            f"{{name: {format_parameter(served[0])}, mimetype: {served[0]}}}"
        )
    if dem is not None and tile_type not in LOSSLESS:
        return f"an elevation archive needs PNG or WebP tiles, not {tile_type.name}"
    return None


def tile_width(data: bytes, tile_type: TileType) -> int | None:
    """The width in pixels of one raster tile, from its header bytes; None when it cannot be read.

    PNG keeps it in the IHDR chunk, JPEG in its start-of-frame segment,
    WebP in the frame header of its lossy, lossless or extended form.
    """
    if tile_type == TileType.PNG and data[:8] == _PNG_SIGNATURE and len(data) >= 24:
        return struct.unpack(">I", data[16:20])[0]
    if tile_type == TileType.JPEG and data[:2] == b"\xff\xd8":
        return _jpeg_width(data)
    if tile_type == TileType.WEBP and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp_width(data)
    return None


def _jpeg_width(data: bytes) -> int | None:
    index = 2
    while index + 9 <= len(data) and data[index] == 0xFF:
        marker = data[index + 1]
        # Start-of-frame markers: all of C0-CF but DHT (C4), JPG (C8) and DAC (CC).
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return struct.unpack(">H", data[index + 7 : index + 9])[0]
        index += 2 + struct.unpack(">H", data[index + 2 : index + 4])[0]
    return None


def _webp_width(data: bytes) -> int | None:
    chunk = data[12:16]
    if chunk == b"VP8 " and len(data) >= 30:
        # Lossy: a three-byte frame tag, the start code 9d 01 2a, then 14 bits of width.
        return struct.unpack("<H", data[26:28])[0] & 0x3FFF
    if chunk == b"VP8L" and len(data) >= 25:
        # Lossless: a signature byte, then the width minus one in 14 bits.
        return (struct.unpack("<I", data[21:25])[0] & 0x3FFF) + 1
    if chunk == b"VP8X" and len(data) >= 30:
        # Extended: the canvas width minus one in 24 bits.
        return int.from_bytes(data[24:27], "little") + 1
    return None
