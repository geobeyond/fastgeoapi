"""The schema of a GeoParquet dataset on a bucket is read once per version of its objects."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

FIXTURE = Path("tests/data/lakes.parquet")
BUCKET = "fastgeoapi-schema"


def _client(endpoint: str):
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )


@pytest.fixture(scope="module")
def bucket(s3_endpoint):
    """The fixture file twice: on its own and under a prefix."""
    client = _client(s3_endpoint)
    client.create_bucket(Bucket=BUCKET)
    client.upload_file(str(FIXTURE), BUCKET, "single/lakes.parquet")
    client.upload_file(str(FIXTURE), BUCKET, "prefix/part-0.parquet")
    return s3_endpoint


@pytest.fixture(autouse=True)
def plain_http(monkeypatch):
    # The local S3 speaks plain HTTP, which obstore takes only through the environment.
    monkeypatch.setenv("AWS_ALLOW_HTTP", "true")


def _options(endpoint: str) -> dict:
    return {
        "endpoint": endpoint.removeprefix("http://"),
        "region": "us-east-1",
        "key_id": "test",
        "secret": "test",
        "url_style": "path",
        "use_ssl": False,
    }


def _with_extra_column(path: Path) -> Path:
    import duckdb

    duckdb.sql(f"COPY (SELECT *, 1 AS extra FROM '{FIXTURE}') TO '{path}' (FORMAT parquet)")
    return path


def _refuse(*args, **kwargs):
    raise AssertionError("the dataset was described again")


def test_a_remote_schema_is_read_through_the_store(bucket, tmp_path):
    from app.provider.geoparquet_schema import remote_schema

    types = remote_schema(
        f"s3://{BUCKET}/single/lakes.parquet", store_options=_options(bucket), cache_dir=tmp_path
    )

    assert types is not None
    assert "name" in types
    assert "geometry" in types


def test_a_prefix_is_described_from_its_objects(bucket, tmp_path):
    from app.provider.geoparquet_schema import remote_schema

    types = remote_schema(
        f"s3://{BUCKET}/prefix/", store_options=_options(bucket), cache_dir=tmp_path
    )

    assert types is not None
    assert "name" in types


def test_unchanged_objects_are_not_described_again(bucket, tmp_path):
    from app.provider import geoparquet_schema

    data = f"s3://{BUCKET}/single/lakes.parquet"
    first = geoparquet_schema.remote_schema(
        data, store_options=_options(bucket), cache_dir=tmp_path
    )

    with patch.object(geoparquet_schema, "_describe", _refuse):
        again = geoparquet_schema.remote_schema(
            data, store_options=_options(bucket), cache_dir=tmp_path
        )

    assert first is not None
    assert "name" in first
    assert again == first


def test_a_changed_object_is_described_again(bucket, tmp_path):
    from app.provider.geoparquet_schema import remote_schema

    data = f"s3://{BUCKET}/changing/lakes.parquet"
    client = _client(bucket)
    client.upload_file(str(FIXTURE), BUCKET, "changing/lakes.parquet")
    before = remote_schema(data, store_options=_options(bucket), cache_dir=tmp_path)
    client.upload_file(
        str(_with_extra_column(tmp_path / "extra.parquet")), BUCKET, "changing/lakes.parquet"
    )

    after = remote_schema(data, store_options=_options(bucket), cache_dir=tmp_path)

    assert before is not None
    assert after is not None
    assert "extra" not in before
    assert "extra" in after


def test_a_broken_cache_entry_is_read_again_and_replaced(bucket, tmp_path):
    from app.provider.geoparquet_schema import remote_schema

    data = f"s3://{BUCKET}/single/lakes.parquet"
    remote_schema(data, store_options=_options(bucket), cache_dir=tmp_path)
    (entry,) = tmp_path.iterdir()
    entry.write_text("{not json")

    types = remote_schema(data, store_options=_options(bucket), cache_dir=tmp_path)

    assert types is not None
    assert "name" in types
    assert json.loads(entry.read_text())["types"] == types


def test_without_a_cache_directory_the_schema_is_still_read(bucket):
    from app.provider.geoparquet_schema import remote_schema

    types = remote_schema(
        f"s3://{BUCKET}/single/lakes.parquet", store_options=_options(bucket), cache_dir=None
    )

    assert types is not None
    assert "name" in types


def test_an_endpoint_from_the_environment_leaves_the_schema_to_duckdb(monkeypatch, tmp_path):
    """The store would list wherever the environment points; DuckDB's secret stays scoped."""
    from app.provider.geoparquet_schema import remote_schema

    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:1")

    types = remote_schema(
        "s3://overturemaps-us-west-2/release/x/",
        store_options={"region": "us-west-2", "skip_signature": True},
        cache_dir=tmp_path,
    )

    assert types is None


def test_a_store_that_cannot_be_listed_leaves_the_schema_to_duckdb(bucket, tmp_path):
    from app.provider import geoparquet_schema

    def unreachable(*args, **kwargs):
        raise OSError("connection refused")

    with patch.object(geoparquet_schema, "load_store", unreachable):
        types = geoparquet_schema.remote_schema(
            f"s3://{BUCKET}/single/lakes.parquet",
            store_options=_options(bucket),
            cache_dir=tmp_path,
        )

    assert types is None


def test_the_provider_takes_an_unchanged_remote_schema_from_the_cache(bucket, tmp_path):
    from app.provider import geoparquet, geoparquet_schema

    definition = {
        "name": "app.provider.geoparquet.GeoParquetProvider",
        "type": "feature",
        "data": f"s3://{BUCKET}/single/lakes.parquet",
        "id_field": "id",
        "geometry_column": "geometry",
        "store_options": _options(bucket),
    }
    with patch.object(geoparquet_schema, "schema_cache_dir", lambda: tmp_path):
        first = geoparquet.GeoParquetProvider(definition)
        with (
            patch.object(geoparquet_schema, "_describe", _refuse),
            patch.object(geoparquet.GeoParquetProvider, "_describe_natively", _refuse),
        ):
            again = geoparquet.GeoParquetProvider(definition)

    assert again.get_fields() == first.get_fields()
    assert len(again.query(limit=10)["features"]) == 4
