"""The bridge guarantees both faces whatever the backend.

fastgeoapi uses the async face (webhook); startup and the future
pygeoapi provider use the sync one: no caller ever decides "how".
"""

from datetime import UTC, datetime

import pytest

from app.provider.storage.base import ObjectMeta
from app.provider.storage.bridge import StorageBridge

_META = ObjectMeta(path="k", size=2, etag="e1", last_modified=datetime.now(UTC))


class _SyncOnly:
    def get(self, path: str) -> bytes:
        return b"ok"

    def head(self, path: str) -> ObjectMeta:
        return _META


class _AsyncOnly:
    async def aget(self, path: str) -> bytes:
        return b"ok"

    async def ahead(self, path: str) -> ObjectMeta:
        return _META


def test_sync_backend_serves_sync():
    assert StorageBridge(_SyncOnly()).read("k") == b"ok"


@pytest.mark.asyncio
async def test_sync_backend_bridged_to_async():
    bridge = StorageBridge(_SyncOnly())
    assert await bridge.aread("k") == b"ok"
    assert (await bridge.astat("k")).etag == "e1"


def test_async_backend_bridged_to_sync():
    bridge = StorageBridge(_AsyncOnly())
    assert bridge.read("k") == b"ok"
    assert bridge.stat("k").etag == "e1"


@pytest.mark.asyncio
async def test_async_backend_serves_async():
    assert await StorageBridge(_AsyncOnly()).aread("k") == b"ok"


def test_obstore_backend_is_native_both_ways(tmp_path):
    from app.provider.storage import load_store

    (tmp_path / "o.txt").write_bytes(b"x")
    bridge = StorageBridge(load_store(str(tmp_path)))
    assert bridge.read("o.txt") == b"x"
    assert bridge.stat("o.txt").size == 1
