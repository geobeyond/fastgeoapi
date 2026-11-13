"""The real renderer reads a remote archive through the loopback server and the range cache."""

from __future__ import annotations

import asyncio
import copy
import dataclasses
import gzip
import io

import pytest
from PIL import Image

from tests.mvt_fixtures import land_archive
from tests.pmtiles_fixtures import write_archive
from tests.range_cache_fixtures import Clock, CountingStore, memory_store, range_cache

pytestmark = pytest.mark.renderer
mlnative = pytest.importorskip("mlnative")
try:
    mlnative.get_binary_path()
except Exception:
    pytest.skip("the mlnative binary is missing", allow_module_level=True)

ROME = (1379000.0, 5140000.0, 1403000.0, 5160000.0)  # EPSG:3857 metres
OPAQUE = (246, 205, 205)  # the default style's fill over white
KEY = "land.pmtiles"
DATA = f"s3://bucket/tiles/{KEY}"


def _share(png: bytes, colour: tuple[int, ...], tolerance: int = 8) -> float:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    data = image.tobytes()
    pixels = [tuple(data[i : i + 3]) for i in range(0, len(data), 3)]
    close = [
        p for p in pixels if all(abs(a - b) <= tolerance for a, b in zip(p, colour, strict=True))
    ]
    return len(close) / len(pixels)


async def _setup(tmp_path, clock=None):
    from app.provider.storage import CachedRanges
    from app.provider.storage.loopback import SOURCES, ensure_range_server

    origin = CountingStore(memory_store())
    origin.put(KEY, land_archive(tmp_path / KEY).read_bytes())
    cached = CachedRanges(origin, KEY, range_cache(memory_store(), clock=clock), source=DATA)
    SOURCES.register(cached)
    return origin, cached, await ensure_range_server()


def _request(cached, server):
    from app.maps.contract import MapRequest
    from app.maps.sources import ObjectUrl, PMTilesSource
    from app.maps.styles import MapLibreStyles

    location = ObjectUrl(resolver=lambda: server.url_for(cached, cached.meta()))
    source = PMTilesSource(
        location, lambda offset, length: cached.at(cached.meta()).read(offset, length)
    )
    style = MapLibreStyles(source).style(None, transparent=False)
    return MapRequest(bbox=ROME, width=256, height=256, style=style)


async def _renderer():
    from app.maps.mlnative import create_renderer

    return await asyncio.to_thread(create_renderer, {"timeout": 30})


async def _teardown(cached):
    from app.provider.storage.loopback import SOURCES, close_range_server

    SOURCES.unregister(cached)
    await cached.cache.drain()
    await close_range_server()


@pytest.mark.asyncio
async def test_a_second_renderer_process_reads_nothing_from_the_archive(tmp_path):
    origin, cached, server = await _setup(tmp_path)
    try:
        request = await asyncio.to_thread(_request, cached, server)
        reads = []
        for _process in range(2):
            renderer = await _renderer()
            try:
                png = await renderer.render(request)
            finally:
                await renderer.aclose()
            assert _share(png, OPAQUE) > 0.9
            reads.append(len(origin.range_reads))
        assert reads[1] == reads[0]  # the second process read nothing from the archive
    finally:
        await _teardown(cached)


@pytest.mark.asyncio
async def test_the_first_render_reads_each_range_of_the_archive_once(tmp_path):
    origin, cached, server = await _setup(tmp_path)
    try:
        request = await asyncio.to_thread(_request, cached, server)
        before = len(origin.range_reads)
        renderer = await _renderer()
        try:
            await renderer.render(request)
        finally:
            await renderer.aclose()
        reads = origin.range_reads[before:]
        assert len(reads) == len(set(reads))
    finally:
        await _teardown(cached)


@pytest.mark.asyncio
async def test_a_new_version_of_the_archive_is_drawn_after_a_style_reload(tmp_path):
    clock = Clock()
    origin, cached, server = await _setup(tmp_path, clock=clock)
    renderer = await _renderer()
    try:
        first = await renderer.render(await asyncio.to_thread(_request, cached, server))
        empty = write_archive(
            tmp_path / "empty.pmtiles",
            {(0, 0, 0): gzip.compress(b"")},
            metadata={"name": "land", "vector_layers": [{"id": "land"}]},
        )
        origin.put(KEY, empty.read_bytes())
        clock.now += 301
        second = await renderer.render(await asyncio.to_thread(_request, cached, server))
    finally:
        await renderer.aclose()
        await _teardown(cached)

    assert _share(first, OPAQUE) > 0.9
    assert _share(second, OPAQUE) < 0.1


@pytest.mark.asyncio
async def test_a_map_after_ranges_that_answered_404_is_drawn(tmp_path):
    """Ranges of a version the server no longer knows answer 404; the next map still draws."""
    from app.maps.contract import RenderError

    _origin, cached, server = await _setup(tmp_path)
    renderer = await _renderer()
    try:
        good = await asyncio.to_thread(_request, cached, server)
        stale_style = copy.deepcopy(good.style)
        for source in stale_style["sources"].values():
            source["url"] = source["url"].rsplit("/", 1)[0] + "/unknown"
        outcome = "drawn"
        try:
            await renderer.render(dataclasses.replace(good, style=stale_style))
        except RenderError:
            outcome = "failed"
        png = await renderer.render(good)
    finally:
        await renderer.aclose()
        await _teardown(cached)

    print(f"a render whose ranges answer 404: {outcome}")
    assert _share(png, OPAQUE) > 0.9
