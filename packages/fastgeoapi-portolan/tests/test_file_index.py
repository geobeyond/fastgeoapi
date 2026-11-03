"""The stac-geoparquet index the ingest writes beside the configuration."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import jsonschema
import pytest

from fastgeoapi_portolan.file_index import IndexRow, delete_index, index_location, write_index

SCHEMA = Path(__file__).parent / "data" / "schemas" / "stac-geoparquet-metadata.json"

ROWS = (
    IndexRow(id="part-0", bbox=(0.0, 0.0, 1.0, 1.0), href="s3://b/part-0.parquet"),
    IndexRow(id="part-1", bbox=(10.0, 10.0, 11.0, 11.0), href="s3://b/part-1.parquet"),
    IndexRow(id="part-2", bbox=(20.0, 20.0, 21.0, 21.0), href="s3://b/part-2.parquet"),
)


def _metadata(location: str) -> dict[str, dict]:
    rows = (
        duckdb.connect()
        .execute("SELECT decode(key), decode(value) FROM parquet_kv_metadata(?)", [location])
        .fetchall()
    )
    return {key: json.loads(value) for key, value in rows}


def test_the_index_location_is_beside_a_local_config(tmp_path):
    location = index_location(str(tmp_path / "pygeoapi-config.yml"), "roads")

    assert location == str(tmp_path.resolve() / "indexes" / "roads.parquet")


def test_the_index_location_is_beside_a_bucket_config():
    assert (
        index_location("s3://bucket/configs/demo.yml", "roads")
        == "s3://bucket/configs/indexes/roads.parquet"
    )


def test_the_written_index_is_valid_stac_geoparquet(tmp_path):
    location = str(tmp_path / "indexes" / "roads.parquet")

    write_index(ROWS, location)

    metadata = _metadata(location)
    jsonschema.validate(metadata["stac-geoparquet"], json.loads(SCHEMA.read_text()))
    assert metadata["geo"]["primary_column"] == "geometry"
    assert metadata["geo"]["columns"]["geometry"]["encoding"] == "WKB"
    stac_geoparquet = pytest.importorskip("stac_geoparquet.arrow")
    parquet = pytest.importorskip("pyarrow.parquet")
    items = list(stac_geoparquet.stac_table_to_items(parquet.read_table(location)))
    assert [
        (item["id"], tuple(item["bbox"]), item["assets"]["data"]["href"]) for item in items
    ] == [(row.id, row.bbox, row.href) for row in ROWS]
    assert items[0]["geometry"]["type"] == "Polygon"


def test_the_index_has_every_required_column(tmp_path):
    location = str(tmp_path / "roads.parquet")

    write_index(ROWS, location)

    columns = {
        name
        for (name, *_) in duckdb.connect()
        .execute("DESCRIBE SELECT * FROM read_parquet(?)", [location])
        .fetchall()
    }
    assert {"stac_extensions", "id", "geometry", "bbox", "links", "assets"} <= columns


def test_deleting_a_missing_index_is_quiet(tmp_path):
    delete_index(str(tmp_path / "indexes" / "gone.parquet"))


@pytest.mark.parametrize("resource_id", ["../../data/part-0", "a/b", "a\\b", "..", ""])
def test_an_id_that_is_not_a_plain_name_has_no_index_location(resource_id):
    with pytest.raises(ValueError, match="file name"):
        index_location("s3://bucket/configs/demo.yml", resource_id)


def test_a_row_across_the_antimeridian_keeps_its_bbox_and_spans_the_world(tmp_path):
    location = str(tmp_path / "roads.parquet")
    across = IndexRow(id="fiji", bbox=(170.0, -20.0, -170.0, -10.0), href="s3://b/fiji.parquet")

    write_index((across,), location)

    metadata = _metadata(location)
    assert metadata["geo"]["columns"]["geometry"]["bbox"] == [-180.0, -20.0, 180.0, -10.0]
    ((bbox,),) = duckdb.connect().execute("SELECT bbox FROM read_parquet(?)", [location]).fetchall()
    assert (bbox["xmin"], bbox["xmax"]) == (170.0, -170.0)
