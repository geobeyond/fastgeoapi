"""From a collection with GeoParquet data to a feature provider."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fastgeoapi_portolan.catalog.testing import PORTOLAN
from fastgeoapi_portolan.geoparquet import PROVIDER, geoparquet, s3_from_https
from fastgeoapi_portolan.handlers import Overrides, Provided, Refused
from fastgeoapi_portolan.reader import Collection

PARQUET = "application/vnd.apache.parquet"
OVERTURE = "https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/release/x/part-0.parquet"


def _parquet(href, **fields):
    return {"href": href, "type": PARQUET, "roles": ["data"], **fields}


def _item(identifier, href, media_type=PARQUET):
    return {
        "type": "Feature",
        "stac_version": "1.1.0",
        "stac_extensions": [],
        "id": identifier,
        "collection": "roads",
        "geometry": {"type": "Point", "coordinates": [12.5, 41.9]},
        "bbox": [12.5, 41.9, 12.5, 41.9],
        "properties": {"datetime": "2026-01-01T00:00:00Z"},
        "links": [{"rel": "collection", "href": "../collection.json", "type": "application/json"}],
        "assets": {"data": {"href": href, "type": media_type, "roles": ["data"]}},
    }


@pytest.fixture
def base(tmp_path):
    return tmp_path.resolve()


def _collection(base, *, assets=None, items=None, **fields):
    """A collection ``roads`` under ``base``, with its items written on disk."""
    folder = base / "roads"
    hrefs = []
    for relative, item in (items or {}).items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(item))
        hrefs.append(str(path))
    document = {
        "type": "Collection",
        "id": "roads",
        "table:columns": [{"name": "id"}, {"name": "geometry"}],
        "assets": assets or {},
        **fields,
    }
    return Collection("roads", str(folder / "collection.json"), document, tuple(hrefs), PORTOLAN)


@pytest.mark.asyncio
async def test_a_collection_level_data_asset_is_the_data(base):
    collection = _collection(base, assets={"data": _parquet("./roads.parquet")})

    provided = await geoparquet(collection, Overrides())

    assert provided == Provided(
        {
            "type": "feature",
            "name": PROVIDER,
            "data": str(base / "roads" / "roads.parquet"),
            "id_field": "id",
            "geometry_column": "geometry",
        },
        (
            "data: collection asset",
            "id_field: id (column name)",
            "geometry_column: geometry (column name)",
        ),
    )


@pytest.mark.asyncio
async def test_items_in_one_folder_give_a_glob(base):
    items = {f"items/part-{n}.json": _item(f"part-{n}", f"./part-{n}.parquet") for n in range(3)}

    provided = await geoparquet(_collection(base, items=items), Overrides())

    assert provided.provider["data"] == f"{base / 'roads' / 'items'}/*.parquet"
    assert "data: glob of 3 items" in provided.choices


@pytest.mark.asyncio
async def test_items_in_different_folders_are_refused(base):
    items = {
        "a/part-0.json": _item("part-0", "./part-0.parquet"),
        "b/part-1.json": _item("part-1", "./part-1.parquet"),
    }

    refused = await geoparquet(_collection(base, items=items), Overrides())

    assert isinstance(refused, Refused)
    assert str(base / "roads" / "a") in refused.reason
    assert str(base / "roads" / "b") in refused.reason


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (OVERTURE, "s3://overturemaps-us-west-2/release/x/part-0.parquet"),
        ("https://s3.us-west-2.amazonaws.com/bucket/key", "s3://bucket/key"),
    ],
)
def test_an_s3_https_url_becomes_an_s3_url_with_its_region(url, expected):
    assert s3_from_https(url) == (expected, {"region": "us-west-2", "skip_signature": True})


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/roads.parquet",
        "https://bucket.s3-website-us-west-2.amazonaws.com/key",
        "s3://bucket/key",
    ],
)
def test_other_urls_are_not_rewritten(url):
    assert s3_from_https(url) is None


@pytest.mark.asyncio
async def test_an_s3_https_data_url_is_read_from_s3(base):
    provided = await geoparquet(_collection(base, assets={"data": _parquet(OVERTURE)}), Overrides())

    assert provided.provider["data"] == "s3://overturemaps-us-west-2/release/x/part-0.parquet"
    assert provided.provider["store_options"] == {"region": "us-west-2", "skip_signature": True}


@pytest.mark.asyncio
async def test_store_options_given_by_the_user_win(base):
    collection = _collection(base, assets={"data": _parquet(OVERTURE)})

    provided = await geoparquet(collection, Overrides(store_options={"region": "eu-central-1"}))

    assert provided.provider["store_options"] == {"region": "eu-central-1", "skip_signature": True}


@pytest.mark.parametrize(
    ("fields", "id_fields", "expected"),
    [
        (
            {"table:primary_key": ["gid"], "table:columns": [{"name": "id"}, {"name": "gid"}]},
            {},
            "gid (table:primary_key)",
        ),
        ({"table:columns": [{"name": "fid"}, {"name": "OBJECTID"}]}, {}, "fid (column name)"),
        (
            {"table:columns": [{"name": "name"}, {"name": "code"}]},
            {"roads": "code"},
            "code (option)",
        ),
        ({"table:columns": [{"name": "name"}]}, {}, Refused),
        (
            {"table:primary_key": ["a", "b"], "table:columns": [{"name": "a"}, {"name": "b"}]},
            {},
            "composite",
        ),
    ],
)
@pytest.mark.asyncio
async def test_the_id_field_follows_the_order_of_preference(base, fields, id_fields, expected):
    fields["table:columns"] = [*fields["table:columns"], {"name": "geometry"}]
    collection = _collection(base, assets={"data": _parquet("./roads.parquet")}, **fields)

    result = await geoparquet(collection, Overrides(id_fields=id_fields))

    if expected is Refused:
        assert isinstance(result, Refused)
        assert "--id-field roads=<column>" in result.reason
    elif expected == "composite":
        assert isinstance(result, Refused)
        assert "composite" in result.reason
    else:
        assert f"id_field: {expected}" in result.choices
        assert result.provider["id_field"] == expected.split()[0]


@pytest.mark.parametrize(
    ("fields", "geometry_columns", "expected"),
    [
        (
            {
                "table:primary_geometry": "shape",
                "table:columns": [{"name": "geometry"}, {"name": "shape"}],
            },
            {},
            "shape (table:primary_geometry)",
        ),
        ({"table:columns": [{"name": "wkb_geometry"}, {"name": "geom"}]}, {}, "geom (column name)"),
        ({"table:columns": [{"name": "the_geom"}]}, {"roads": "the_geom"}, "the_geom (option)"),
        ({"table:columns": [{"name": "name"}]}, {}, Refused),
    ],
)
@pytest.mark.asyncio
async def test_the_geometry_column_follows_the_order_of_preference(
    base, fields, geometry_columns, expected
):
    fields["table:columns"] = [{"name": "id"}, *fields["table:columns"]]
    collection = _collection(base, assets={"data": _parquet("./roads.parquet")}, **fields)

    result = await geoparquet(collection, Overrides(geometry_columns=geometry_columns))

    if expected is Refused:
        assert isinstance(result, Refused)
        assert "--geometry-column roads=<column>" in result.reason
    else:
        assert f"geometry_column: {expected}" in result.choices
        assert result.provider["geometry_column"] == expected.split()[0]


@pytest.mark.asyncio
async def test_a_collection_without_parquet_is_not_this_handlers(base):
    tiles = {
        "tiles": {"href": "./roads.pmtiles", "type": "application/vnd.pmtiles", "roles": ["visual"]}
    }
    scenes = {"scenes/a.json": _item("a", "./a.tif", "image/tiff; application=geotiff")}

    assert await geoparquet(_collection(base, assets=tiles), Overrides()) is None
    assert await geoparquet(_collection(base, items=scenes), Overrides()) is None


@pytest.mark.asyncio
async def test_a_declared_partition_glob_is_the_data(base):
    collection = _collection(base, **{"partition:glob": "part=*/*.parquet"})

    provided = await geoparquet(collection, Overrides())

    assert provided.provider["data"] == f"{base / 'roads'}/part=*/*.parquet"
    assert "data: partition:glob" in provided.choices


@pytest.mark.asyncio
async def test_an_s3_alternate_is_the_data_url(base):
    data = _parquet(OVERTURE, alternate={"s3": {"href": "s3://bucket/x.parquet"}})

    provided = await geoparquet(_collection(base, assets={"data": data}), Overrides())

    assert provided.provider["data"] == "s3://bucket/x.parquet"
    assert "data: s3 alternate" in provided.choices
    assert "store_options" not in provided.provider


@pytest.mark.asyncio
async def test_a_partitioned_collection_with_a_nonconforming_item_is_refused(base):
    bad = _item("part-1", "./part-1.parquet")
    bad["bbox"] = [12.5, 41.9, 200.0, 41.9]
    items = {"part=0/part-0.json": _item("part-0", "./part-0.parquet"), "part=1/part-1.json": bad}
    collection = _collection(base, items=items, **{"partition:glob": "part=*/*.parquet"})

    refused = await geoparquet(collection, Overrides())

    assert isinstance(refused, Refused)
    assert str(base / "roads" / "part=1" / "part-1.json") in refused.reason
    assert str(base / "roads" / "part=0" / "part-0.json") not in refused.reason


@pytest.mark.asyncio
async def test_column_names_match_whatever_their_case(base):
    columns = {"table:columns": [{"name": "OBJECTID"}, {"name": "Geometry"}]}
    collection = _collection(base, assets={"data": _parquet("./roads.parquet")}, **columns)

    provided = await geoparquet(collection, Overrides())

    assert (provided.provider["id_field"], provided.provider["geometry_column"]) == (
        "OBJECTID",
        "Geometry",
    )


@pytest.mark.asyncio
async def test_the_columns_of_the_items_are_read_from_their_properties(base):
    item = _item("part-0", "./part-0.parquet")
    item["properties"]["table:columns"] = [{"name": "gid"}, {"name": "geom"}]
    collection = _collection(base, items={"items/part-0.json": item}, **{"table:columns": []})

    provided = await geoparquet(collection, Overrides())

    assert (provided.provider["id_field"], provided.provider["geometry_column"]) == ("gid", "geom")


@pytest.mark.asyncio
async def test_a_parquet_media_type_with_parameters_is_parquet(base):
    asset = {**_parquet("./roads.parquet"), "type": f"{PARQUET}; profile=geoparquet"}

    provided = await geoparquet(_collection(base, assets={"data": asset}), Overrides())

    assert isinstance(provided, Provided)


@pytest.mark.asyncio
async def test_many_folders_are_named_in_short(base):
    items = {f"f{n}/part-{n}.json": _item(f"part-{n}", f"./part-{n}.parquet") for n in range(5)}

    refused = await geoparquet(_collection(base, items=items), Overrides())

    assert refused.reason.endswith("and 2 more")
    assert "5 folders" in refused.reason


@pytest.mark.asyncio
async def test_the_item_limits_come_from_the_overrides(base):
    items = {f"items/part-{n}.json": _item(f"part-{n}", f"./part-{n}.parquet") for n in range(3)}
    collection = _collection(base, items=items)

    too_many = await geoparquet(collection, Overrides(max_documents=2))
    too_large = await geoparquet(collection, Overrides(max_document_bytes=100))

    assert isinstance(too_many, Refused)
    assert too_many.reason == (
        "the items could not be read: the collection links 3 items, more than the 2 the reader reads"
    )
    assert isinstance(too_large, Refused)
    assert "larger than 100 bytes" in too_large.reason


REMOTE = "https://example.org/cat/roads/collection.json"
LOCAL_FROM_REMOTE = "is on the local disk, linked from a remote catalog"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields",
    [
        {"assets": {"data": _parquet("file:///srv/data/other.parquet")}},
        {"assets": {}, "partition:glob": "file:///srv/data/*.parquet"},
    ],
)
async def test_a_remote_collection_cannot_point_at_local_data(fields):
    columns = [{"name": "id"}, {"name": "geometry"}]
    document = {"type": "Collection", "id": "roads", "table:columns": columns, **fields}
    collection = Collection("roads", REMOTE, document, (), PORTOLAN)

    refused = await geoparquet(collection, Overrides())

    assert isinstance(refused, Refused)
    assert refused.reason.startswith("the data file:///srv/data/")
    assert refused.reason.endswith(LOCAL_FROM_REMOTE)


@pytest.mark.asyncio
async def test_a_remote_collection_cannot_point_at_local_data_through_its_items(base):
    on_disk = _collection(
        base, items={"items/part-0.json": _item("part-0", "file:///srv/data/part-0.parquet")}
    )
    # Plain STAC: the Portolan profile already wants https asset hrefs in items.
    collection = Collection("roads", REMOTE, on_disk.document, on_disk.item_hrefs, None)

    refused = await geoparquet(collection, Overrides())

    assert isinstance(refused, Refused)
    assert refused.reason == f"the data file:///srv/data/*.parquet {LOCAL_FROM_REMOTE}"


@pytest.mark.asyncio
async def test_items_that_cannot_be_read_refuse_the_collection(base):
    collection = _collection(base, items={"items/part-0.json": _item("part-0", "./part-0.parquet")})
    Path(collection.item_hrefs[0]).unlink()

    refused = await geoparquet(collection, Overrides())

    assert isinstance(refused, Refused)
    assert refused.reason == "the items could not be read: it does not exist"


@pytest.mark.asyncio
async def test_an_item_that_is_not_json_refuses_the_collection(base):
    collection = _collection(base, items={"items/part-0.json": _item("part-0", "./part-0.parquet")})
    Path(collection.item_hrefs[0]).write_text("not JSON")

    refused = await geoparquet(collection, Overrides())

    assert isinstance(refused, Refused)
    assert refused.reason.endswith("the document is not JSON")
