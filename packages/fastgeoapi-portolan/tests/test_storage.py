"""Reading objects on disk, behind http(s) and in a bucket."""

from __future__ import annotations

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import obstore
import pytest
from obstore.store import HTTPStore, S3Store

from fastgeoapi_portolan.catalog.protocols import MAX_DOCUMENT_BYTES, DocumentTooLargeError
from fastgeoapi_portolan.storage import (
    ObstoreTransport,
    read_bytes,
    read_range,
    store_and_key,
    to_obstore_config,
)

EXTRAS = "https://overturemaps-extras-us-west-2.s3.us-west-2.amazonaws.com"


@pytest.fixture
def served(tmp_path):
    """``tmp_path`` over HTTP on loopback."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_store_options_are_spelled_for_obstore():
    config = to_obstore_config(
        {"region": "us-west-2", "endpoint": "minio.local:9000", "use_ssl": False, "key_id": "k"},
        "s3://bucket",
    )

    assert config == {
        "region": "us-west-2",
        "endpoint": "http://minio.local:9000",
        "access_key_id": "k",
    }


def test_a_virtual_hosted_endpoint_is_given_the_bucket():
    config = to_obstore_config(
        {"endpoint": "fly.storage.tigris.dev", "url_style": "vhost"}, "s3://demo/cat/"
    )

    assert config["endpoint"] == "https://demo.fly.storage.tigris.dev"


@pytest.mark.asyncio
async def test_a_local_file_is_read(tmp_path):
    (tmp_path / "a.json").write_bytes(b'{"a": 1}')

    assert await read_bytes(str(tmp_path / "a.json")) == b'{"a": 1}'
    assert await read_range(str(tmp_path / "a.json"), 1, 3) == b'"a"'


@pytest.mark.asyncio
async def test_bucket_options_do_not_reach_an_https_store(tmp_path, served):
    (tmp_path / "style.json").write_bytes(b"{}")

    data = await read_bytes(f"{served}/style.json", {"region": "us-west-2", "skip_signature": True})

    assert data == b"{}"


def test_an_https_url_of_a_bucket_is_read_over_plain_https():
    """obstore takes an amazonaws.com URL for a bucket, and a bucket store signs every request."""
    store, key = store_and_key(f"{EXTRAS}/tiles/x/divisions.pmtiles", None)

    assert isinstance(store, HTTPStore)
    assert key == "divisions.pmtiles"


@pytest.mark.network
@pytest.mark.asyncio
async def test_a_public_archive_in_a_bucket_is_read_over_https_without_credentials(monkeypatch):
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    bucket = S3Store("overturemaps-extras-us-west-2", region="us-west-2", skip_signature=True)
    releases = obstore.list_with_delimiter(bucket, "tiles/")["common_prefixes"]

    header = await read_range(f"{EXTRAS}/{max(releases)}/divisions.pmtiles", 0, 7)

    assert header == b"PMTiles"


@pytest.mark.asyncio
async def test_a_missing_object_is_reported_as_a_missing_file(served):
    with pytest.raises(FileNotFoundError):
        await read_bytes(f"{served}/nowhere.json")


BUCKET = "portolan-catalog"
# The discard port: nobody listens, a connection here is refused at once.
NOBODY_LISTENS = "http://127.0.0.1:9"


@pytest.fixture(scope="module")
def bucket(s3_endpoint):
    """One object on the local S3."""
    boto3 = pytest.importorskip("boto3")
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    client.put_object(Bucket=BUCKET, Key="cat/catalog.json", Body=b'{"id": "root"}')
    return {
        "endpoint": s3_endpoint.removeprefix("http://"),
        "use_ssl": False,
        "url_style": "path",
        "region": "us-east-1",
        "key_id": "test",
        "secret": "test",
    }


@pytest.mark.asyncio
async def test_a_bucket_on_plain_http_is_read_with_its_store_options_alone(bucket, monkeypatch):
    monkeypatch.delenv("AWS_ALLOW_HTTP", raising=False)

    data = await read_bytes(f"s3://{BUCKET}/cat/catalog.json", bucket)

    assert data == b'{"id": "root"}'
    assert await read_range(f"s3://{BUCKET}/cat/catalog.json", 2, 2, bucket) == b"id"


@pytest.mark.asyncio
async def test_an_explicit_endpoint_wins_over_the_environment(bucket, monkeypatch):
    monkeypatch.delenv("AWS_ALLOW_HTTP", raising=False)
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", NOBODY_LISTENS)

    assert await read_bytes(f"s3://{BUCKET}/cat/catalog.json", bucket) == b'{"id": "root"}'
    assert os.environ["AWS_ENDPOINT_URL_S3"] == NOBODY_LISTENS


class Forbidden(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_error(403)


@pytest.mark.asyncio
async def test_a_store_failure_reaches_the_walk_as_an_oserror():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Forbidden)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with pytest.raises(OSError, match="403"):
            await ObstoreTransport().read(f"http://127.0.0.1:{server.server_address[1]}/x.json")
    finally:
        server.shutdown()


@pytest.mark.asyncio
async def test_a_document_over_the_cap_is_refused(tmp_path):
    (tmp_path / "big.json").write_bytes(b"x" * 20)

    with pytest.raises(DocumentTooLargeError, match="larger than 10 bytes"):
        await ObstoreTransport(max_bytes=10).read(str(tmp_path / "big.json"))
    assert await ObstoreTransport(max_bytes=20).read(str(tmp_path / "big.json")) == b"x" * 20
    assert ObstoreTransport().max_bytes == MAX_DOCUMENT_BYTES
