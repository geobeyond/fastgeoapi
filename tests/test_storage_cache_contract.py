"""The storage operations a cache needs: list with metadata, delete, read a range of one version."""

import pytest
from obstore.store import MemoryStore

BLOB = bytes(range(256))


@pytest.fixture(params=["local", "memory"])
def store(request, tmp_path):
    from app.provider.storage import ObstoreStore, load_store

    store = load_store(str(tmp_path)) if request.param == "local" else ObstoreStore(MemoryStore())
    store.put("a/blob.bin", BLOB)
    return store


def test_a_conditional_range_read_at_the_current_etag_returns_the_bytes(store):
    etag = store.head("a/blob.bin").etag
    assert store.get_range("a/blob.bin", 10, 5, if_match=etag) == BLOB[10:15]


@pytest.mark.asyncio
async def test_the_async_conditional_read_returns_the_bytes_too(store):
    etag = (await store.ahead("a/blob.bin")).etag
    assert await store.aget_range("a/blob.bin", 250, 6, if_match=etag) == BLOB[250:256]


def test_a_conditional_read_at_another_etag_says_the_object_changed(store):
    from app.provider.storage import ObjectChangedError

    with pytest.raises(ObjectChangedError):
        store.get_range("a/blob.bin", 0, 4, if_match='"another"')


@pytest.mark.asyncio
async def test_the_async_conditional_read_says_the_object_changed_too(store):
    from app.provider.storage import ObjectChangedError

    with pytest.raises(ObjectChangedError):
        await store.aget_range("a/blob.bin", 0, 4, if_match='"another"')


def test_entries_give_path_size_and_date_of_every_object_under_a_prefix(store):
    store.put("a/b/other.bin", b"xyz")

    entries = sorted(store.entries("a"), key=lambda entry: entry.path)

    assert [(entry.path, entry.size) for entry in entries] == [
        ("a/b/other.bin", 3),
        ("a/blob.bin", 256),
    ]
    assert all(entry.last_modified is not None for entry in entries)


@pytest.mark.asyncio
async def test_async_entries_match(store):
    assert [entry.path for entry in await store.aentries("a")] == ["a/blob.bin"]


def test_delete_removes_the_object(store):
    store.delete("a/blob.bin")

    with pytest.raises(FileNotFoundError):
        store.get("a/blob.bin")


@pytest.mark.asyncio
async def test_deleting_a_missing_object_is_not_an_error(store):
    store.delete("a/missing.bin")
    await store.adelete("a/missing.bin")


def test_is_remote_names_buckets_and_http_urls_only():
    from app.provider.storage import is_remote

    assert is_remote("s3://bucket/tiles/a.pmtiles")
    assert is_remote("https://example.org/a.pmtiles")
    assert not is_remote("file:///tmp/a.pmtiles")
    assert not is_remote("/tmp/a.pmtiles")
    assert not is_remote("tiles/a.pmtiles")
