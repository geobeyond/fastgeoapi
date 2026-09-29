"""The PMTiles provider reads a remote archive through the range cache."""

import gzip

import pytest

from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.range_cache_fixtures import BrokenStore, Clock, CountingStore, memory_store, range_cache

DATA = "s3://bucket/tiles/roads.pmtiles"
KEY = "roads.pmtiles"


def _archive(path, tiles):
    return write_archive(path, tiles).read_bytes()


def _provider(origin, cache, zoom=(0, 1)):
    from app.provider.pmtiles import PMTilesProvider
    from app.provider.storage import CachedRanges

    provider = PMTilesProvider(
        {
            "type": "tile",
            "name": "app.provider.pmtiles.PMTilesProvider",
            "data": DATA,
            "options": {"zoom": {"min": zoom[0], "max": zoom[1]}, "schemes": ["WebMercatorQuad"]},
            "format": {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"},
        }
    )
    provider.cached_ranges = CachedRanges(origin, KEY, cache, source=DATA)
    return provider


@pytest.fixture
def origin(tmp_path):
    store = CountingStore(memory_store())
    store.put(KEY, _archive(tmp_path / "v1.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)}))
    return store


@pytest.mark.asyncio
async def test_a_restarted_provider_serves_its_tiles_without_reading_the_archive(origin):
    cache_store = memory_store()
    first_cache, second_cache = range_cache(cache_store), range_cache(cache_store)

    assert await _provider(origin, first_cache).aget_tiles(z=0, x=0, y=0) == b"tile 0/0/0"
    reads = len(origin.range_reads)
    # A new process: nothing in memory, the same cache on disk.
    assert await _provider(origin, second_cache).aget_tiles(z=0, x=0, y=0) == b"tile 0/0/0"

    assert len(origin.range_reads) == reads
    await first_cache.drain()
    await second_cache.drain()


def test_the_sync_face_reads_through_the_cache_too(origin):
    cache_store = memory_store()

    assert _provider(origin, range_cache(cache_store)).get_tiles(z=0, x=0, y=0) == b"tile 0/0/0"
    reads = len(origin.range_reads)
    assert _provider(origin, range_cache(cache_store)).get_tiles(z=0, x=0, y=0) == b"tile 0/0/0"

    assert len(origin.range_reads) == reads


@pytest.mark.asyncio
async def test_an_archive_rewritten_in_place_is_opened_again(origin, tmp_path):
    clock = Clock()
    cache = range_cache(memory_store(), clock=clock)
    provider = _provider(origin, cache)
    assert await provider.aget_tiles(z=0, x=0, y=0) == b"tile 0/0/0"

    origin.put(KEY, _archive(tmp_path / "v2.pmtiles", {(0, 0, 0): gzip.compress(b"new 0/0/0")}))
    clock.now += 301

    assert await provider.aget_tiles(z=0, x=0, y=0) == b"new 0/0/0"
    await cache.drain()


@pytest.mark.asyncio
async def test_a_read_that_finds_the_archive_changed_is_tried_again_on_the_new_one(tmp_path):
    origin = CountingStore(memory_store())
    tiles = {(1, 0, 0): TILE_BYTES(1, 0, 0), (1, 1, 0): TILE_BYTES(1, 1, 0)}
    origin.put(KEY, _archive(tmp_path / "v1.pmtiles", tiles))
    cache = range_cache(memory_store())
    provider = _provider(origin, cache)
    assert await provider.aget_tiles(z=1, x=0, y=0) == b"tile 1/0/0"

    newer = {(1, 0, 0): gzip.compress(b"new 1/0/0"), (1, 1, 0): gzip.compress(b"new 1/1/0")}
    origin.put(KEY, _archive(tmp_path / "v2.pmtiles", newer))

    # Within the TTL the old version is still trusted: the tile not read yet misses,
    # its read finds the archive changed, and the provider opens the new one.
    assert await provider.aget_tiles(z=1, x=1, y=0) == b"new 1/1/0"
    await cache.drain()


@pytest.mark.asyncio
async def test_a_broken_cache_store_still_serves_the_tiles(origin):
    provider = _provider(origin, range_cache(BrokenStore()))

    assert await provider.aget_tiles(z=0, x=0, y=0) == b"tile 0/0/0"
