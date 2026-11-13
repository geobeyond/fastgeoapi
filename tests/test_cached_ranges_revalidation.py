"""A reader that cannot wait takes the known version, while the HEAD past the TTL runs behind."""

import asyncio
from typing import Any

import pytest

from tests.range_cache_fixtures import Clock, CountingStore, memory_store, range_cache

KEY = "roads.pmtiles"


class GatedStore(CountingStore):
    """A store whose HEAD waits until the test opens the gate, or fails while ``failing``.

    Past the gate a HEAD takes ``delay`` seconds more, as on a loaded machine.
    """

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)
        self.gate = asyncio.Event()
        self.failing = False
        self.delay = 0.0

    async def ahead(self, path: str) -> Any:
        self.heads += 1
        await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failing:
            raise OSError("the store is unreachable")
        return await self.inner.ahead(path)


def _cached(store, clock):
    from app.provider.storage import CachedRanges

    return CachedRanges(
        store, KEY, range_cache(memory_store(), clock=clock), source="s3://b/" + KEY
    )


async def _settled(cached) -> None:
    """Let the revalidation in flight, if any, finish.

    It is awaited, with a deadline: its HEAD runs on the store's own thread,
    so no number of turns of the loop is sure to be enough.
    """
    task = cached._revalidating
    if task is not None:
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_the_first_version_is_awaited():
    store, clock = GatedStore(memory_store()), Clock()
    store.put(KEY, b"v1")
    store.gate.set()
    cached = _cached(store, clock)

    meta = await cached.ameta_without_waiting()

    assert store.heads == 1
    assert cached.known_meta() == meta


@pytest.mark.asyncio
async def test_a_fresh_version_is_taken_without_a_head():
    store, clock = GatedStore(memory_store()), Clock()
    store.put(KEY, b"v1")
    store.gate.set()
    cached = _cached(store, clock)
    first = await cached.ameta_without_waiting()

    again = await cached.ameta_without_waiting()

    assert again == first
    assert store.heads == 1


@pytest.mark.asyncio
async def test_past_the_ttl_the_known_version_is_taken_while_the_head_runs_behind():
    store, clock = GatedStore(memory_store()), Clock()
    store.put(KEY, b"v1")
    store.gate.set()
    cached = _cached(store, clock)
    first = await cached.ameta_without_waiting()
    store.gate.clear()
    store.put(KEY, b"v2, rewritten in place")
    clock.now += 301

    stale = await asyncio.wait_for(cached.ameta_without_waiting(), timeout=1)
    store.gate.set()
    await _settled(cached)

    assert stale == first
    known = cached.known_meta()
    assert known is not None
    assert known.etag != first.etag


@pytest.mark.asyncio
async def test_one_revalidation_runs_at_a_time():
    store, clock = GatedStore(memory_store()), Clock()
    store.put(KEY, b"v1")
    store.gate.set()
    cached = _cached(store, clock)
    await cached.ameta_without_waiting()
    store.gate.clear()
    clock.now += 301

    for _ in range(5):
        await cached.ameta_without_waiting()
    store.gate.set()
    await _settled(cached)

    assert store.heads == 2


@pytest.mark.asyncio
async def test_a_failed_revalidation_keeps_the_known_version():
    store, clock = GatedStore(memory_store()), Clock()
    store.put(KEY, b"v1")
    store.gate.set()
    cached = _cached(store, clock)
    first = await cached.ameta_without_waiting()
    store.failing = True
    clock.now += 301

    assert await cached.ameta_without_waiting() == first
    await _settled(cached)

    assert cached.known_meta() == first


@pytest.mark.asyncio
async def test_a_revalidation_slower_than_the_loop_is_waited_for():
    """The HEAD runs on another thread: on a loaded machine it outlasts many turns of the loop."""
    store, clock = GatedStore(memory_store()), Clock()
    store.put(KEY, b"v1")
    store.gate.set()
    cached = _cached(store, clock)
    first = await cached.ameta_without_waiting()
    store.delay = 0.2
    store.put(KEY, b"v2, rewritten in place")
    clock.now += 301

    await cached.ameta_without_waiting()
    await _settled(cached)

    assert cached.known_meta() != first
