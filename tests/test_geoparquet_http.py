"""A GeoParquet file at an http(s) URL, read by DuckDB itself.

``app.*`` is imported at the top of this module, nowhere else.
"""

import io
import re
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.provider.duckdb_ import DuckDBUnavailableError, protocol_for
from app.provider.geoparquet import GeoParquetProvider

DATA = Path(__file__).parent / "data"


class RangeHandler(SimpleHTTPRequestHandler):
    """Answers a ``Range`` request with 206, as the hosts of real datasets do."""

    def send_head(self):
        asked = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        path = Path(self.translate_path(self.path))
        if asked is None or not path.is_file():
            return super().send_head()
        data = path.read_bytes()
        start = int(asked[1])
        end = int(asked[2]) if asked[2] else len(data) - 1
        body = data[start : end + 1]
        self.send_response(206)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Range", f"bytes {start}-{start + len(body) - 1}/{len(data)}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return io.BytesIO(body)

    def log_message(self, format, *args):
        """Keep the test output quiet."""


@pytest.fixture(scope="module")
def served():
    """``tests/data`` over HTTP on loopback, with byte ranges."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(RangeHandler, directory=str(DATA)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _provider(data: str) -> GeoParquetProvider:
    return GeoParquetProvider(
        {
            "name": "GeoParquet",
            "type": "feature",
            "data": data,
            "id_field": "id",
            "geometry_column": "geometry",
        }
    )


def test_an_http_url_is_read_by_duckdb_itself():
    assert protocol_for("https://example.org/lakes.parquet") is None
    assert protocol_for("http://127.0.0.1:8000/lakes.parquet") is None


def test_a_geoparquet_file_at_an_http_url_is_served(served):
    provider = _provider(f"{served}/lakes.parquet")

    result = provider.query(bbox=[11.0, 41.0, 13.0, 43.0], limit=10)
    first = result["features"][0]

    assert first["geometry"]["type"] == "Point"
    assert provider.get(first["id"])["id"] == first["id"]


@pytest.mark.parametrize("path", ["/*.parquet", "/folder/"])
def test_a_glob_or_a_folder_at_an_http_url_is_refused_with_the_reason(served, path):
    with pytest.raises(DuckDBUnavailableError, match="HTTP cannot list"):
        _provider(f"{served}{path}")
