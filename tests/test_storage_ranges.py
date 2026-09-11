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
