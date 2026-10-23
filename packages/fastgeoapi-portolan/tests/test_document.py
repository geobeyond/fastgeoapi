"""Reading a configuration document, and writing it back only if nobody changed it meanwhile."""

from __future__ import annotations

import os

import obstore
import pytest
from obstore.store import MemoryStore

from fastgeoapi_portolan.document import (
    ConcurrentEditError,
    Document,
    read_document,
    write_document,
)

BUCKET = "portolan-config"


def test_a_local_document_round_trips(tmp_path):
    path = tmp_path / "pygeoapi-config.yml"
    path.write_text("resources: {}\n")

    document = read_document(str(path))
    write_document(document, "resources:\n  roads: {}\n")

    assert document.text == "resources: {}\n"
    assert path.read_text() == "resources:\n  roads: {}\n"
    assert read_document(str(path)).version != document.version


def test_a_local_document_changed_meanwhile_is_not_written(tmp_path):
    path = tmp_path / "pygeoapi-config.yml"
    path.write_text("resources: {}\n")
    document = read_document(str(path))
    path.write_text("resources: {lakes: {}}\n")

    with pytest.raises(ConcurrentEditError, match="changed since it was read"):
        write_document(document, "resources:\n  roads: {}\n")

    assert path.read_text() == "resources: {lakes: {}}\n"


def test_a_local_document_touched_meanwhile_is_not_written(tmp_path):
    path = tmp_path / "pygeoapi-config.yml"
    path.write_text("resources: {}\n")
    document = read_document(str(path))
    stat = path.stat()
    # Same size, another modification time: an editor saved the same bytes.
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    with pytest.raises(ConcurrentEditError):
        write_document(document, "resources:\n  roads: {}\n")


def test_a_local_document_keeps_its_permissions_and_its_link(tmp_path):
    target = tmp_path / "real.yml"
    target.write_text("resources: {}\n")
    target.chmod(0o640)
    link = tmp_path / "pygeoapi-config.yml"
    link.symlink_to(target)

    write_document(read_document(str(link)), "resources:\n  roads: {}\n")

    assert link.is_symlink()
    assert target.read_text() == "resources:\n  roads: {}\n"
    assert target.stat().st_mode & 0o777 == 0o640


def test_a_missing_document_is_a_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_document(str(tmp_path / "nowhere.yml"))
    with pytest.raises(FileNotFoundError):
        read_document("nowhere.yml", store=MemoryStore())


def test_an_object_round_trips_in_memory():
    store = MemoryStore()
    obstore.put(store, "pygeoapi-config.yml", b"resources: {}\n")

    document = read_document("pygeoapi-config.yml", store=store)
    write_document(document, "resources:\n  roads: {}\n", store=store)

    assert document.text == "resources: {}\n"
    assert bytes(obstore.get(store, "pygeoapi-config.yml").bytes()) == b"resources:\n  roads: {}\n"


def test_an_object_changed_meanwhile_is_not_written():
    store = MemoryStore()
    obstore.put(store, "pygeoapi-config.yml", b"resources: {}\n")
    document = read_document("pygeoapi-config.yml", store=store)
    obstore.put(store, "pygeoapi-config.yml", b"resources: {lakes: {}}\n")

    with pytest.raises(ConcurrentEditError, match="changed since it was read"):
        write_document(document, "resources:\n  roads: {}\n", store=store)

    assert bytes(obstore.get(store, "pygeoapi-config.yml").bytes()) == b"resources: {lakes: {}}\n"


@pytest.fixture
def bucket(s3_endpoint, monkeypatch):
    """A configuration document on the local S3, and the options to reach it."""
    boto3 = pytest.importorskip("boto3")
    monkeypatch.delenv("AWS_ALLOW_HTTP", raising=False)
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    client.put_object(Bucket=BUCKET, Key="pygeoapi-config.yml", Body=b"resources: {}\n")
    store_options = {
        "endpoint": s3_endpoint.removeprefix("http://"),
        "use_ssl": False,
        "url_style": "path",
        "region": "us-east-1",
        "key_id": "test",
        "secret": "test",
    }
    return client, store_options


def test_an_object_in_a_bucket_round_trips(bucket):
    client, store_options = bucket
    location = f"s3://{BUCKET}/pygeoapi-config.yml"

    document = read_document(location, store_options)
    write_document(document, "resources:\n  roads: {}\n", store_options)

    body = client.get_object(Bucket=BUCKET, Key="pygeoapi-config.yml")["Body"].read()
    assert body == b"resources:\n  roads: {}\n"


def test_an_object_in_a_bucket_changed_meanwhile_is_not_written(bucket):
    client, store_options = bucket
    location = f"s3://{BUCKET}/pygeoapi-config.yml"
    document = read_document(location, store_options)
    client.put_object(Bucket=BUCKET, Key="pygeoapi-config.yml", Body=b"resources: {lakes: {}}\n")

    with pytest.raises(ConcurrentEditError):
        write_document(document, "resources:\n  roads: {}\n", store_options)


def test_an_object_without_a_version_is_not_written_blindly():
    store = MemoryStore()
    obstore.put(store, "pygeoapi-config.yml", b"resources: {}\n")
    document = Document("pygeoapi-config.yml", "resources: {}\n", ("", ""))

    with pytest.raises(ValueError, match="no version to write against"):
        write_document(document, "resources:\n  roads: {}\n", store=store)

    assert bytes(obstore.get(store, "pygeoapi-config.yml").bytes()) == b"resources: {}\n"
