"""obstore backend: real LocalStore on tmp_path, remote schemes at construction only."""

import pytest

from app.provider.storage import load_store, split_source
from app.provider.storage.base import ObjectMeta, ObjectStore


@pytest.fixture
def local_store(tmp_path):
    (tmp_path / "pygeoapi-config.yml").write_bytes(b"server:\n  bind:\n    host: 0.0.0.0\n")
    return load_store(str(tmp_path))


def test_local_store_satisfies_protocol(local_store):
    assert isinstance(local_store, ObjectStore)


def test_get_returns_bytes(local_store):
    data = local_store.get("pygeoapi-config.yml")
    assert isinstance(data, bytes)
    assert data.startswith(b"server:")


@pytest.mark.asyncio
async def test_aget_returns_same_bytes(local_store):
    assert await local_store.aget("pygeoapi-config.yml") == local_store.get("pygeoapi-config.yml")


def test_head_returns_meta_with_etag(local_store):
    meta = local_store.head("pygeoapi-config.yml")
    assert isinstance(meta, ObjectMeta)
    assert meta.size > 0
    assert meta.etag  # LocalStore derives the etag from mtime+size


def test_etag_changes_when_object_changes(tmp_path):
    target = tmp_path / "pygeoapi-config.yml"
    target.write_bytes(b"server: {}\n")
    store = load_store(str(tmp_path))
    first = store.head("pygeoapi-config.yml").etag
    target.write_bytes(b"server: {}\nlogging: {}\n")  # different size => different etag
    assert store.head("pygeoapi-config.yml").etag != first


def test_missing_object_raises_file_not_found(local_store):
    with pytest.raises(FileNotFoundError):
        local_store.get("missing.yml")


@pytest.mark.parametrize(
    ("source", "base", "key"),
    [
        ("s3://bucket/dir/config.yml", "s3://bucket/dir/", "config.yml"),
        ("gs://bucket/config.yml", "gs://bucket/", "config.yml"),
        ("az://container/a/b/c.yml", "az://container/a/b/", "c.yml"),
    ],
)
def test_split_source_urls(source, base, key):
    assert split_source(source) == (base, key)


def test_split_source_local_relative(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base, key = split_source("pygeoapi-config.yml")
    assert key == "pygeoapi-config.yml"
    assert base == str(tmp_path)


def test_load_store_builds_s3_store_without_network():
    # Store construction contacts no network and needs no credentials.
    store = load_store("s3://no-such-bucket/prefix/")
    assert isinstance(store, ObjectStore)


def test_put_roundtrip(tmp_path):
    store = load_store(str(tmp_path))
    store.put("artifact.yml", b"openapi: 3.0.2\n")
    assert store.get("artifact.yml") == b"openapi: 3.0.2\n"


@pytest.mark.asyncio
async def test_aput_roundtrip(tmp_path):
    store = load_store(str(tmp_path))
    await store.aput("artifact.yml", b"openapi: 3.0.2\n")
    assert await store.aget("artifact.yml") == b"openapi: 3.0.2\n"
