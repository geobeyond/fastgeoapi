"""Byte-range reads through the storage layer (ADR-0010, decision 7)."""

import pytest

from app.provider.storage import StorageBridge, load_store
from app.provider.storage.base import ObjectStore

BLOB = bytes(range(256))


@pytest.fixture
def store(tmp_path):
    (tmp_path / "blob.bin").write_bytes(BLOB)
    return load_store(str(tmp_path))


def test_the_local_store_still_satisfies_the_protocol_with_ranges(store):
    assert isinstance(store, ObjectStore)


def test_get_range_returns_exactly_the_requested_bytes(store):
    assert store.get_range("blob.bin", 10, 5) == BLOB[10:15]


@pytest.mark.asyncio
async def test_aget_range_matches_the_sync_read(store):
    assert await store.aget_range("blob.bin", 250, 6) == BLOB[250:256]


def test_get_ranges_keeps_the_order_of_the_request(store):
    assert store.get_ranges("blob.bin", [(250, 6), (0, 3)]) == [BLOB[250:256], BLOB[0:3]]
    assert store.get_ranges("blob.bin", []) == []


@pytest.mark.asyncio
async def test_aget_ranges_matches_the_sync_read(store):
    assert await store.aget_ranges("blob.bin", [(0, 3), (128, 2)]) == [BLOB[0:3], BLOB[128:130]]
    assert await store.aget_ranges("blob.bin", []) == []


class _SyncOnly:
    def get_range(self, path, offset, length):
        return BLOB[offset : offset + length]


class _AsyncOnly:
    async def aget_range(self, path, offset, length):
        return BLOB[offset : offset + length]


def test_the_bridge_fills_the_missing_sync_side():
    assert StorageBridge(_SyncOnly()).read_range("x", 1, 2) == BLOB[1:3]
    assert StorageBridge(_AsyncOnly()).read_range("x", 1, 2) == BLOB[1:3]


@pytest.mark.asyncio
async def test_the_bridge_fills_the_missing_async_side():
    assert await StorageBridge(_SyncOnly()).aread_range("x", 1, 2) == BLOB[1:3]
    assert await StorageBridge(_AsyncOnly()).aread_range("x", 1, 2) == BLOB[1:3]


# --- ADR-0011: a cold burst must not read the same bytes once per request ------


class _CountingAsync:
    """Async-only ByteRanges that counts fetches and answers slowly enough to overlap."""

    def __init__(self):
        self.fetches: list[tuple[int, int]] = []

    def read(self, offset, length):
        self.fetches.append((offset, length))
        return BLOB[offset : offset + length]

    async def aread(self, offset, length):
        import asyncio

        self.fetches.append((offset, length))
        await asyncio.sleep(0.01)
        return BLOB[offset : offset + length]

    def read_many(self, ranges):
        return [self.read(o, n) for o, n in ranges]

    async def aread_many(self, ranges):
        return [await self.aread(o, n) for o, n in ranges]


@pytest.mark.asyncio
async def test_identical_awaited_reads_in_flight_share_one_fetch():
    import asyncio

    from app.provider.storage import SingleFlightRanges

    inner = _CountingAsync()
    ranges = SingleFlightRanges(inner)
    results = await asyncio.gather(*(ranges.aread(0, 127) for _ in range(50)))
    assert results == [BLOB[0:127]] * 50
    assert inner.fetches == [(0, 127)]  # one fetch for fifty concurrent readers
    assert await ranges.aread(0, 127) == BLOB[0:127]
    assert len(inner.fetches) == 2  # a later read fetches again: no caching, only de-duplication


def test_the_sync_side_passes_through_untouched():
    from app.provider.storage import SingleFlightRanges

    inner = _CountingAsync()
    ranges = SingleFlightRanges(inner)
    assert ranges.read(10, 5) == BLOB[10:15]
    assert ranges.inner is inner
