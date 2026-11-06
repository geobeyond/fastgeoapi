"""``--check-ids``: the id column of each GeoParquet collection, read on its own."""

from __future__ import annotations

import json
import struct
import sys

import pytest
from click.testing import CliRunner
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from ruamel.yaml import YAML

from fastgeoapi_portolan.command import ingest_command
from fastgeoapi_portolan.geoparquet import duplicate_ids

duckdb = pytest.importorskip("duckdb", reason="--check-ids reads the data with DuckDB")

PARQUET = "application/vnd.apache.parquet"
DATA = {"data": {"href": "./roads.parquet", "type": PARQUET, "roles": ["data"]}}
CONFIG = "resources:\n  lakes:\n    type: collection\n"
# A point in WKB, as a GeoParquet file stores its geometry.
POINT = struct.pack("<BIdd", 1, 1, 12.5, 41.9).hex()


def _run(*arguments):
    return CliRunner().invoke(ingest_command(validator=lambda: None), list(arguments))


def _write_parquet(path, ids):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = ", ".join("(NULL)" if value is None else f"({value})" for value in ids)
    connection = duckdb.connect()
    connection.execute(
        f"COPY (SELECT id, from_hex('{POINT}') AS geometry FROM (VALUES {rows}) AS t(id)) "
        f"TO '{path}' (FORMAT parquet)"
    )
    connection.close()


def _write_archive(path):
    header = {
        "tile_type": TileType.MVT,
        "tile_compression": Compression.NONE,
        "min_lon_e7": 123000000,
        "min_lat_e7": 418000000,
        "max_lon_e7": 126000000,
        "max_lat_e7": 420000000,
        "center_zoom": 0,
        "center_lon_e7": 124500000,
        "center_lat_e7": 419000000,
    }
    with path.open("wb") as handle:
        writer = Writer(handle)
        writer.write_tile(zxy_to_tileid(0, 0, 0), b"tile")
        writer.finalize(header, {"vector_layers": [{"id": "roads", "minzoom": 0, "maxzoom": 0}]})


def _write_catalog(folder, ids, *, assets=DATA):
    """A catalog with one collection, ``roads``, whose data holds ``ids``."""
    collection = {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": [],
        "id": "roads",
        "title": "Roads",
        "description": "The roads collection.",
        "license": "CC-BY-4.0",
        "extent": {
            "spatial": {"bbox": [[12.3, 41.8, 12.6, 42.0]]},
            "temporal": {"interval": [["2026-01-01T00:00:00Z", None]]},
        },
        "table:columns": [{"name": "id"}, {"name": "geometry"}],
        "assets": assets,
        "links": [
            {"rel": "root", "href": "../catalog.json", "type": "application/json"},
            {"rel": "parent", "href": "../catalog.json", "type": "application/json"},
        ],
    }
    (folder / "roads").mkdir(parents=True)
    (folder / "roads" / "collection.json").write_text(json.dumps(collection))
    if ids is not None:
        _write_parquet(folder / "roads" / "roads.parquet", ids)
    catalog = {
        "type": "Catalog",
        "stac_version": "1.1.0",
        "id": "example",
        "description": "An example catalog.",
        "links": [
            {"rel": "root", "href": "./catalog.json", "type": "application/json"},
            {"rel": "child", "href": "./roads/collection.json", "type": "application/json"},
        ],
    }
    (folder / "catalog.json").write_text(json.dumps(catalog))
    return folder / "catalog.json"


@pytest.fixture
def base(tmp_path):
    return tmp_path.resolve()


def test_unique_ids_pass(base):
    root = _write_catalog(base / "cat", [1, 2, 3])

    result = _run("--from-portolan", str(root), "--check-ids", "--strict")

    assert result.exit_code == 0, result.output
    assert list(YAML(typ="safe").load(result.stdout)["resources"]) == ["roads"]
    assert "not unique" not in result.stderr


@pytest.mark.asyncio
async def test_the_count_is_the_rows_without_an_id_of_their_own(base):
    data = base / "roads.parquet"
    _write_parquet(data, [1, 2, 2, 3, 3, 3, None])

    assert await duplicate_ids(str(data), "id", {}) == 4


@pytest.mark.asyncio
async def test_the_rows_of_a_file_without_the_column_have_no_id(base):
    _write_parquet(base / "a.parquet", [1, 2])
    connection = duckdb.connect()
    connection.execute(
        f"COPY (SELECT 'x' AS name UNION ALL SELECT 'y') TO '{base / 'b.parquet'}' (FORMAT parquet)"
    )
    connection.close()

    assert await duplicate_ids(str(base / "*.parquet"), "id", {}) == 2


@pytest.mark.asyncio
async def test_the_column_is_quoted_as_an_identifier(base):
    quoted = '"my ""id"""'
    connection = duckdb.connect()
    connection.execute(
        f"COPY (SELECT * FROM (VALUES (1), (1)) AS t({quoted})) TO '{base / 'a.parquet'}' "
        "(FORMAT parquet)"
    )
    connection.close()

    assert await duplicate_ids(str(base / "a.parquet"), 'my "id"', {}) == 1


@pytest.fixture
def bucket(base, s3_endpoint):
    """Two files on the local S3 that share one id, and the options to reach them."""
    boto3 = pytest.importorskip("boto3")
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket="check-ids")
    for name, ids in (("a", [1, 2]), ("b", [2, 3])):
        _write_parquet(base / f"{name}.parquet", ids)
        client.put_object(
            Bucket="check-ids",
            Key=f"roads/{name}.parquet",
            Body=(base / f"{name}.parquet").read_bytes(),
        )
    return {
        "endpoint": s3_endpoint.removeprefix("http://"),
        "use_ssl": False,
        "url_style": "path",
        "region": "us-east-1",
        "key_id": "test",
        "secret": "test",
    }


@pytest.mark.asyncio
async def test_ids_in_a_bucket_are_read_with_its_store_options(bucket):
    assert await duplicate_ids("s3://check-ids/roads/*.parquet", "id", bucket) == 1


@pytest.mark.asyncio
async def test_a_quote_in_a_store_option_stays_in_the_value(bucket):
    options = {**bucket, "secret": "te'st"}

    assert await duplicate_ids("s3://check-ids/roads/*.parquet", "id", options) == 1


def test_duplicate_ids_are_reported_with_their_count(base):
    root = _write_catalog(base / "cat", [1, 2, 2, None])

    reported = _run("--from-portolan", str(root), "--check-ids")
    refused = _run("--from-portolan", str(root), "--check-ids", "--strict")

    assert reported.exit_code == 0, reported.output
    assert "roads: the id column id is not unique: 2 rows repeat an id or have none" in (
        reported.stderr
    )
    assert "roads" in YAML(typ="safe").load(reported.stdout)["resources"]
    assert refused.exit_code == 1
    assert "--strict: 1 collections whose ids repeat or could not be checked, nothing printed" in (
        refused.stderr
    )
    assert "resources:" not in refused.stdout


def test_strict_writes_nothing_when_the_ids_are_not_unique(base):
    root = _write_catalog(base / "cat", [1, 1])
    config = base / "pygeoapi-config.yml"
    config.write_text(CONFIG)

    result = _run("--from-portolan", str(root), "--into", str(config), "--check-ids", "--strict")

    assert result.exit_code == 1
    assert "--strict: 1 collections whose ids repeat or could not be checked, nothing written" in (
        result.stderr
    )
    assert config.read_text() == CONFIG


def test_only_the_geoparquet_provider_is_checked(base):
    tiles = {"href": "./roads.pmtiles", "type": "application/vnd.pmtiles", "roles": ["visual"]}
    root = _write_catalog(base / "cat", [1, 2], assets={**DATA, "tiles": tiles})
    _write_archive(base / "cat" / "roads" / "roads.pmtiles")

    result = _run("--from-portolan", str(root), "--check-ids", "--strict")

    assert result.exit_code == 0, result.output
    providers = YAML(typ="safe").load(result.stdout)["resources"]["roads"]["providers"]
    assert [provider["type"] for provider in providers] == ["feature", "tile"]


def test_ids_that_cannot_be_read_are_reported(base):
    root = _write_catalog(base / "cat", None)

    reported = _run("--from-portolan", str(root), "--check-ids")
    refused = _run("--from-portolan", str(root), "--check-ids", "--strict")

    assert reported.exit_code == 0, reported.output
    assert "roads: the ids could not be checked:" in reported.stderr
    assert refused.exit_code == 1
    assert "1 collections whose ids repeat or could not be checked" in refused.stderr


def test_without_duckdb_the_option_names_the_package(base, monkeypatch):
    root = _write_catalog(base / "cat", [1, 2, 3])
    monkeypatch.setitem(sys.modules, "duckdb", None)

    result = _run("--from-portolan", str(root), "--check-ids")

    assert result.exit_code == 1
    assert "--check-ids needs duckdb: pip install duckdb" in result.stderr


@pytest.mark.network
@pytest.mark.asyncio
async def test_the_ids_of_overture_division_boundaries_are_unique():
    """The public bucket, read without signing, in its latest release."""
    import obstore
    from obstore.store import S3Store

    store = S3Store("overturemaps-us-west-2", region="us-west-2", skip_signature=True)
    releases = obstore.list_with_delimiter(store, "release/")["common_prefixes"]
    data = f"s3://overturemaps-us-west-2/{max(releases)}/theme=divisions/type=division_boundary/*"

    options = {"region": "us-west-2", "skip_signature": True}
    assert await duplicate_ids(data, "id", options) == 0
