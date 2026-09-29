"""The range cache keeps entries by key, deletes the oldest past its cap, hides store failures."""

import stat
import threading
from unittest.mock import patch

import pytest

from tests.range_cache_fixtures import BrokenStore, Clock, CountingStore, memory_store, range_cache


@pytest.fixture
def warnings():
    from loguru import logger

    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(sink)


@pytest.mark.asyncio
async def test_an_entry_put_is_got_back():
    cache = range_cache(memory_store())
    await cache.aput("s/v/0-3", b"abc")
    assert await cache.aget("s/v/0-3", 3) == b"abc"
    await cache.drain()


def test_the_sync_face_keeps_entries_too():
    cache = range_cache(memory_store())
    cache.put("s/v/0-3", b"abc")
    assert cache.get("s/v/0-3", 3) == b"abc"


@pytest.mark.asyncio
async def test_a_missing_entry_is_none():
    assert await range_cache(memory_store()).aget("s/v/0-3", 3) is None


@pytest.mark.asyncio
async def test_an_entry_of_the_wrong_length_is_a_miss_and_is_deleted():
    store = memory_store()
    store.put("s/v/0-3", b"ab")
    cache = range_cache(store)

    assert await cache.aget("s/v/0-3", 3) is None
    with pytest.raises(FileNotFoundError):
        store.get("s/v/0-3")


def test_a_key_names_the_source_the_version_and_the_range():
    from app.provider.storage import RangeCache

    assert RangeCache.key("src", "ver", 127, 42) == "src/ver/127-42"


def test_digests_are_short_and_path_safe():
    from app.provider.storage.cache import digest

    value = digest('s3://bucket/a key/"etag"')
    assert len(value) == 32
    assert value.isalnum()


def _entry(index: int) -> str:
    """The key of an entry as the cache writes it; three-digit offsets sort like numbers."""
    from app.provider.storage import RangeCache
    from app.provider.storage.cache import digest

    return RangeCache.key(digest("s"), digest("v"), 100 + index, 10)


@pytest.mark.asyncio
async def test_a_sweep_deletes_the_entries_written_first_down_to_nine_tenths_of_the_cap():
    store = memory_store()
    for index in range(12):
        store.put(_entry(index), bytes(10))  # 120 bytes, written in order

    await range_cache(store, max_bytes=100).asweep()

    kept = sorted(entry.path for entry in store.entries())
    assert kept == [_entry(index) for index in range(3, 12)]  # 90 bytes left


@pytest.mark.asyncio
async def test_under_the_cap_a_sweep_deletes_nothing():
    store = memory_store()
    store.put(_entry(0), bytes(50))

    await range_cache(store, max_bytes=100).asweep()

    assert [entry.path for entry in store.entries()] == [_entry(0)]


@pytest.mark.asyncio
async def test_a_sweep_leaves_the_objects_the_cache_did_not_write():
    store = memory_store()
    store.put("roads.pmtiles", bytes(200))  # an operator's file, written before the entries
    for index in range(12):
        store.put(_entry(index), bytes(10))

    await range_cache(store, max_bytes=100).asweep()

    kept = sorted(entry.path for entry in store.entries())
    assert kept == sorted(["roads.pmtiles", *(_entry(index) for index in range(3, 12))])


@pytest.mark.asyncio
async def test_the_first_write_sweeps_and_then_every_tenth_of_the_cap():
    cache = range_cache(memory_store(), max_bytes=100)
    sweeps: list[int] = []
    original = cache.asweep

    async def counted() -> None:
        sweeps.append(1)
        await original()

    with patch.object(cache, "asweep", counted):
        for index in range(5):
            await cache.aput(f"s/v/{index:02d}", bytes(5))
            await cache.drain()

    assert len(sweeps) == 3  # the first write, then at 10 and at 20 bytes written


@pytest.mark.asyncio
async def test_a_range_larger_than_a_tenth_of_the_cap_is_not_kept():
    store = CountingStore(memory_store())
    cache = range_cache(store, max_bytes=100)

    await cache.aput("s/v/big", bytes(11))

    assert store.writes == []


@pytest.mark.asyncio
async def test_a_broken_cache_store_never_fails_a_read_or_a_write():
    cache = range_cache(BrokenStore())

    assert await cache.aget("s/v/0-3", 3) is None
    await cache.aput("s/v/0-3", b"abc")
    await cache.asweep()
    assert cache.get("s/v/0-3", 3) is None
    cache.put("s/v/0-3", b"abc")
    await cache.drain()


def test_warnings_about_the_same_failure_come_once_a_minute(warnings):
    clock = Clock()
    cache = range_cache(BrokenStore(), clock=clock)

    for _ in range(3):
        cache.get("s/v/0-3", 3)
    clock.now += 61
    cache.get("s/v/0-3", 3)

    reads = [message for message in warnings if "range cache read failed" in message]
    assert len(reads) == 2
    assert all("read-only" not in message for message in reads)


def test_a_local_cache_directory_is_created_private_at_its_first_use(tmp_path):
    from app.provider.storage import RangeCache

    location = tmp_path / "cache" / "ranges"
    cache = RangeCache.at(str(location), max_bytes=1 << 20)

    assert not location.exists()  # building the cache touches no disk
    cache.put("s/v/0-3", b"abc")
    assert stat.S_IMODE(location.stat().st_mode) == 0o700
    assert cache.get("s/v/0-3", 3) == b"abc"


def test_concurrent_writes_of_one_entry_never_show_a_partial_entry(tmp_path):
    """Two workers may write the same entry: a reader sees one whole write or the other."""
    from app.provider.storage import load_store

    store = load_store(str(tmp_path))
    size = 1 << 20
    whole: list[bool] = []
    done = threading.Event()

    def write(byte: bytes) -> None:
        for _ in range(20):
            store.put("s/v/0-1048576", byte * size)

    def read() -> None:
        while not done.is_set():
            try:
                data = store.get("s/v/0-1048576")
            except FileNotFoundError:
                continue
            whole.append(len(data) == size and data == data[:1] * size)

    reader = threading.Thread(target=read)
    writers = [threading.Thread(target=write, args=(value,)) for value in (b"a", b"b")]
    reader.start()
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join()
    done.set()
    reader.join()

    assert whole
    assert all(whole)
