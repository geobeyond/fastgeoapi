"""The reference transport: http(s), local paths and file URLs, with the standard library."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fastgeoapi_portolan.catalog import urllib_transport
from fastgeoapi_portolan.catalog.urllib_transport import UrllibTransport


@pytest.fixture
def served(tmp_path):
    """``tmp_path`` over HTTP on loopback."""
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_a_document_over_http_is_read(tmp_path, served):
    (tmp_path / "catalog.json").write_bytes(b'{"id": "root"}')

    assert UrllibTransport().read(f"{served}/catalog.json") == b'{"id": "root"}'


def test_a_404_is_a_missing_document(served):
    with pytest.raises(FileNotFoundError):
        UrllibTransport().read(f"{served}/nowhere.json")


def test_a_local_path_and_a_file_url_are_read(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_bytes(b"{}")

    assert UrllibTransport().read(str(path)) == b"{}"
    assert UrllibTransport().read(path.as_uri()) == b"{}"


def test_a_missing_local_file_is_a_missing_document(tmp_path):
    with pytest.raises(FileNotFoundError):
        UrllibTransport().read(str(tmp_path / "nowhere.json"))


def test_a_document_over_the_cap_is_refused(tmp_path, served, monkeypatch):
    (tmp_path / "big.json").write_bytes(b"x" * 20)
    monkeypatch.setattr(urllib_transport, "MAX_DOCUMENT_BYTES", 10)

    with pytest.raises(OSError, match="larger than 10 bytes"):
        UrllibTransport().read(str(tmp_path / "big.json"))
    with pytest.raises(OSError, match="larger than 10 bytes"):
        UrllibTransport().read(f"{served}/big.json")


def test_a_bucket_needs_another_transport():
    with pytest.raises(OSError, match="the s3 scheme needs another transport"):
        UrllibTransport().read("s3://bucket/catalog.json")
