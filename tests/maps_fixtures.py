"""A renderer that draws nothing, for the tests that cannot run MapLibre Native."""

from __future__ import annotations

import asyncio
import struct
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.maps.contract import MapRequest


def tiny_png(width: int = 1, height: int = 1) -> bytes:
    """A valid, fully transparent RGBA PNG of the given size."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + b"\x00\x00\x00\x00" * width
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


class FakeRenderer:
    """Records the requests; ``options["fake"]`` picks how it behaves."""

    instances: list[FakeRenderer] = []
    gate: asyncio.Event | None = None

    def __init__(self, options: dict):
        self.options = options
        self.requests: list[MapRequest] = []
        self.closed = False
        self.calls = 0

    async def render(self, request: MapRequest) -> bytes:
        self.calls += 1
        self.requests.append(request)
        behaviour = self.options.get("fake", "ok")
        if behaviour == "slow":
            await asyncio.sleep(10)
        if behaviour == "gate" and FakeRenderer.gate is not None:
            await FakeRenderer.gate.wait()
        if behaviour == "crash-once" and len(FakeRenderer.instances) == 1:
            # Imported here, not at the top: tests that purge `app.*` from
            # sys.modules re-import the contract, and the provider then
            # catches the new class, not the one bound at import time.
            from app.maps.contract import RenderError

            raise RenderError("boom")
        if behaviour == "oserror-once" and len(FakeRenderer.instances) == 1:
            raise OSError("could not load pmtiles://bucket/a.pmtiles?X-Amz-Signature=SECRET")
        return tiny_png(request.width, request.height)

    async def aclose(self) -> None:
        self.closed = True


def create_fake_renderer(options: dict) -> FakeRenderer:
    """The factory a provider definition names in ``options.renderer``."""
    renderer = FakeRenderer(options)
    FakeRenderer.instances.append(renderer)
    return renderer


def map_provider(archive: Path, **options) -> dict:
    """A map provider definition over a local PMTiles archive, with the fake renderer."""
    return {
        "type": "map",
        "name": "app.provider.maplibre.MapLibreMapProvider",
        "data": str(archive),
        "storage_crs": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "options": {"renderer": "tests.maps_fixtures.create_fake_renderer", **options},
        "format": {"name": "png", "mimetype": "image/png"},
    }
