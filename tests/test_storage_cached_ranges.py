"""Versioned, cached ranged reads of one object."""

import asyncio

import pytest

from tests.range_cache_fixtures import Clock, CountingStore, memory_store, range_cache

BLOB = bytes(range(256)) * 4
KEY = "tiles/roads.pmtiles"


def _cached(origin, cache=None, clock=None):
    from app.provider.storage import CachedRanges

    cache = cache or range_cache(memory_store(), clock=clock)
    return CachedRanges(origin, KEY, cache, source=f"s3://bucket/{KEY}")


@pytest.fixture
def origin():
    store = CountingStore(memory_store())
    store.put(KEY, BLOB)
    return store


@pytest.mark.asyncio
async def test_a_second_read_of_a_range_does_not_reach_the_object(origin):
    cached = _cached(origin)
    ranges = cached.at(await cached.ameta())

    assert await ranges.aread(10, 20) == BLOB[10:30]
    assert await ranges.aread(10, 20) == BLOB[10:30]
    assert origin.range_reads == [(10, 20)]
    await cached.cache.drain()


def test_the_sync_face_reads_through_the_cache_too(origin):
    cached = _cached(origin)
    ranges = cached.at(cached.meta())

    assert ranges.read(0, 4) == BLOB[:4]
    assert ranges.read(0, 4) == BLOB[:4]
    assert origin.range_reads == [(0, 4)]


@pytest.mark.asyncio
async def test_ten_concurrent_misses_make_one_read_and_one_write(origin):
    cache_store = CountingStore(memory_store())
    cached = _cached(origin, cache=range_cache(cache_store))
    ranges = cached.at(await cached.ameta())

    results = await asyncio.gather(*(ranges.aread(0, 127) for _ in range(10)))

    assert results == [BLOB[:127]] * 10
    assert origin.range_reads == [(0, 127)]
    assert len(cache_store.writes) == 1
    await cached.cache.drain()


@pytest.mark.asyncio
async def test_the_version_is_trusted_until_revalidate_seconds_pass(origin):
    clock = Clock()
    cached = _cached(origin, clock=clock)

    await cached.ameta()
    await cached.ameta()
    assert origin.heads == 1
    clock.now += 301
    await cached.ameta()
    assert origin.heads == 2


@pytest.mark.asyncio
async def test_a_new_version_reads_the_object_again_under_new_keys(origin):
    clock = Clock()
    cached = _cached(origin, clock=clock)
    old = await cached.ameta()
    await cached.at(old).aread(0, 8)

    origin.put(KEY, bytes(1024))  # rewritten in place: a new ETag
    clock.now += 301
    new = await cached.ameta()

    assert new.etag != old.etag
    assert await cached.at(new).aread(0, 8) == bytes(8)
    assert origin.range_reads == [(0, 8), (0, 8)]
    await cached.cache.drain()


@pytest.mark.asyncio
async def test_a_miss_that_finds_the_object_changed_raises_and_forgets_the_version(origin):
    from app.provider.storage import ObjectChangedError

    cached = _cached(origin)
    pinned = cached.at(await cached.ameta())
    origin.put(KEY, bytes(1024))

    with pytest.raises(ObjectChangedError):
        await pinned.aread(0, 8)
    await cached.ameta()
    assert origin.heads == 2  # asked again at once, before the TTL


@pytest.mark.asyncio
async def test_an_object_without_etag_is_read_through_and_never_kept(origin):
    from app.provider.storage import ObjectMeta
    from app.provider.storage.cache import UNVERSIONED, version_of

    cached = _cached(origin)
    unversioned = ObjectMeta(path=KEY, size=len(BLOB), etag=None, last_modified=None)
    ranges = cached.at(unversioned)

    assert await ranges.aread(0, 4) == BLOB[:4]
    assert await ranges.aread(0, 4) == BLOB[:4]
    assert origin.range_reads == [(0, 4), (0, 4)]
    assert version_of(unversioned) == UNVERSIONED


@pytest.mark.asyncio
async def test_the_last_two_versions_are_known_by_their_digest(origin):
    from app.provider.storage.cache import version_of

    clock = Clock()
    cached = _cached(origin, clock=clock)
    versions = []
    for content in (b"one", b"two", b"three"):
        origin.put(KEY, content * 100)
        clock.now += 301
        versions.append(await cached.ameta())

    assert cached.known(version_of(versions[0])) is None
    assert cached.known(version_of(versions[1])) == versions[1]
    assert cached.known(version_of(versions[2])) == versions[2]


@pytest.mark.asyncio
async def test_a_short_read_at_the_end_of_the_object_is_not_kept(origin):
    cache_store = CountingStore(memory_store())
    cached = _cached(origin, cache=range_cache(cache_store))
    ranges = cached.at(await cached.ameta())

    assert await ranges.aread(1020, 10) == BLOB[1020:]
    assert cache_store.writes == []
