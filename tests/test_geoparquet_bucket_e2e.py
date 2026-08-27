"""The GeoParquet provider against a real S3 endpoint, served locally.

Everything else exercises the provider through `LocalStore`, which shares
the reader path but never sends an HTTP request. That leaves the part
that actually broke in production untested: how the dataset is *reached*
— endpoint, signing, addressing style, and expanding a prefix into files.

MiniStack is a local AWS emulator, so this stays offline and
deterministic. What it deliberately does NOT test is the part that made
the cloud interesting in the first place: latency, DuckDB's block cache,
row-group pruning measured in seconds. An emulator answers those
dishonestly, so they stay with the measurements on a real deployment
(ADR-0004).
"""

import os
import socket

# ruff: ignore[suspicious-subprocess-import]
import subprocess
import time
from pathlib import Path

import pytest

FIXTURE = Path("tests/data/lakes.parquet")
BUCKET = "fastgeoapi-test"
KEY = "lakes/lakes.parquet"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def s3_endpoint():
    """A local S3, started for the module and torn down after it."""
    pytest.importorskip("boto3", reason="the bucket end-to-end test needs boto3")
    port = _free_port()
    process = subprocess.Popen(
        ["ministack"],  # ruff: ignore[start-process-with-partial-path]
        env={**os.environ, "GATEWAY_PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        process.kill()
        pytest.fail("MiniStack did not come up within 30s")

    yield f"http://127.0.0.1:{port}"

    process.terminate()
    process.wait(timeout=10)


@pytest.fixture(scope="module")
def bucket(s3_endpoint):
    """The fixture file, uploaded to a bucket on the local S3."""
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    client.upload_file(str(FIXTURE), BUCKET, KEY)
    return s3_endpoint


def _provider(endpoint: str, data: str):
    from app.provider.geoparquet import GeoParquetProvider

    return GeoParquetProvider(
        {
            "name": "app.provider.geoparquet.GeoParquetProvider",
            "type": "feature",
            "data": data,
            "id_field": "id",
            "geometry_column": "geometry",
            "time_field": "observed_at",
            "store_options": {
                "endpoint": endpoint.removeprefix("http://"),
                "region": "us-east-1",
                "key_id": "test",
                "secret": "test",
                "url_style": "path",
                "use_ssl": False,
            },
        }
    )


def test_a_single_object_is_served_over_s3(bucket):
    """The plainest case: one object, named in full."""
    features = _provider(bucket, f"s3://{BUCKET}/{KEY}").query(limit=10)["features"]
    assert sorted(f["properties"]["name"] for f in features) == [
        "Bolsena",
        "Bracciano",
        "Garda",
        "Geneva",
    ]


def test_a_prefix_is_expanded_into_files(bucket):
    """A directory-shaped source has to become a glob DuckDB can expand.

    This is the path that broke twice: first because no wildcard survived
    the obstore bridge, then because listing through obstore inherited
    the process environment. Neither shows up against a local path.
    """
    features = _provider(bucket, f"s3://{BUCKET}/lakes").query(limit=10)["features"]
    assert len(features) == 4


def test_filters_are_pushed_down_over_s3(bucket):
    """bbox, CQL2 and datetime have to work the same way they do locally."""
    from pygeofilter.parsers.cql2_text import parse

    provider = _provider(bucket, f"s3://{BUCKET}/{KEY}")

    in_lazio = provider.query(bbox=[11.5, 41.8, 12.5, 42.8])["features"]
    assert sorted(f["properties"]["name"] for f in in_lazio) == ["Bolsena", "Bracciano"]

    big = provider.query(filterq=parse("area_km2 > 300"))["features"]
    assert sorted(f["properties"]["name"] for f in big) == ["Garda", "Geneva"]

    recent = provider.query(datetime_="2023-01-01T00:00:00Z/..")["features"]
    assert sorted(f["properties"]["name"] for f in recent) == ["Garda", "Geneva"]


def test_the_dataset_endpoint_beats_the_environment(bucket, monkeypatch):
    """A dataset must be read where it lives, not where the process banks.

    This is the failure that cost a production afternoon: a deployment
    keeping its own data on an S3-compatible service carries
    `AWS_ENDPOINT_URL_S3` for it, and every read of a dataset living
    elsewhere was sent to that endpoint instead. DuckDB's secret is
    scoped to the dataset, which is what makes this pass.
    """
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "belonging-to-another-store")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "belonging-to-another-store")

    features = _provider(bucket, f"s3://{BUCKET}/{KEY}").query(limit=10)["features"]
    assert len(features) == 4
