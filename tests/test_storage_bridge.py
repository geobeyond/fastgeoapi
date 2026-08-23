"""The bridge guarantees both faces whatever the backend.

fastgeoapi uses the async face (webhook); startup and the future
pygeoapi provider use the sync one: no caller ever decides "how".

Every import here stays at module level ON PURPOSE. Other test modules
purge ``app.*`` from ``sys.modules`` in their fixtures, so an import
inside a test would build a SECOND ``ObjectMeta`` class: the bridge
captured at collection time would then return an instance the typeguard
run rejects against its own annotation ("ObjectMeta is not an instance
of ObjectMeta").
"""

from datetime import UTC, datetime

import pytest

from app.provider.storage import load_store
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
    (tmp_path / "o.txt").write_bytes(b"x")
    bridge = StorageBridge(load_store(str(tmp_path)))
    assert bridge.read("o.txt") == b"x"
    assert bridge.stat("o.txt").size == 1


class _SyncWriter:
    def __init__(self):
        self.written: dict[str, bytes] = {}

    def put(self, path: str, data: bytes) -> None:
        self.written[path] = data


class _AsyncWriter:
    def __init__(self):
        self.written: dict[str, bytes] = {}

    async def aput(self, path: str, data: bytes) -> None:
        self.written[path] = data


@pytest.mark.asyncio
async def test_sync_writer_bridged_to_awrite():
    backend = _SyncWriter()
    await StorageBridge(backend).awrite("k", b"v")
    assert backend.written == {"k": b"v"}


def test_async_writer_bridged_to_write():
    backend = _AsyncWriter()
    StorageBridge(backend).write("k", b"v")
    assert backend.written == {"k": b"v"}


def test_obstore_backend_writes_native(tmp_path):
    bridge = StorageBridge(load_store(str(tmp_path)))
    bridge.write("o.txt", b"x")
    assert bridge.read("o.txt") == b"x"
