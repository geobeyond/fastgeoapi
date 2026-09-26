"""The CQL2 operation is described only where the provider filters.

pygeoapi writes ``POST /collections/{id}/items`` with a CQL2 JSON body
for every feature collection. Only some providers use the filter they
receive: the SQL ones, Elasticsearch, OpenSearch, Oracle and our
GeoParquet provider. The others, CSV and GeoJSON among them, ignore it,
and the request returns the whole collection as if it had been filtered.
"""

from pathlib import Path

import pytest
from pygeoapi.util import yaml_load

from app.pygeoapi.factory import build_openapi
from app.pygeoapi.openapi import drop_unfiltered_cql2_operations


@pytest.fixture(scope="module")
def document() -> dict:
    return build_openapi(yaml_load(Path("tests/data/pygeoapi-config.yml").open()))


def test_a_geojson_collection_has_no_cql2_operation(document):
    assert "post" not in document["paths"]["/collections/lakes/items"]


def test_a_csv_collection_has_no_cql2_operation(document):
    assert "post" not in document["paths"]["/collections/obs/items"]


def test_the_items_listing_stays(document):
    assert "get" in document["paths"]["/collections/lakes/items"]


def _items(*collections: str) -> dict:
    return {
        "paths": {
            f"/collections/{name}/items": {
                "get": {"operationId": f"get{name}"},
                "post": {"operationId": f"getCQL2{name}"},
            }
            for name in collections
        }
    }


def _collection(name: str, *, editable: bool = False, ptype: str = "feature") -> dict:
    return {
        "type": "collection",
        "providers": [{"type": ptype, "name": name, "editable": editable, "data": "x"}],
    }


def test_a_provider_that_filters_keeps_the_operation():
    config = {
        "resources": {
            "db": _collection("PostgreSQL"),
            "parquet": _collection("app.provider.geoparquet.GeoParquetProvider"),
        }
    }

    doc = drop_unfiltered_cql2_operations(_items("db", "parquet"), config)

    assert "post" in doc["paths"]["/collections/db/items"]
    assert "post" in doc["paths"]["/collections/parquet/items"]


def test_a_provider_that_ignores_the_filter_loses_it():
    config = {"resources": {"csv": _collection("CSV")}}

    doc = drop_unfiltered_cql2_operations(_items("csv"), config)

    assert "post" not in doc["paths"]["/collections/csv/items"]
    assert "get" in doc["paths"]["/collections/csv/items"]


def test_an_editable_provider_keeps_the_post_it_needs_to_add_items():
    config = {"resources": {"edit": _collection("GeoJSON", editable=True)}}

    doc = drop_unfiltered_cql2_operations(_items("edit"), config)

    assert "post" in doc["paths"]["/collections/edit/items"]


def test_the_record_provider_is_the_one_that_counts():
    """pygeoapi uses the record provider when a collection has one."""
    config = {
        "resources": {
            "catalogue": {
                "type": "collection",
                "providers": [
                    {"type": "feature", "name": "CSV", "data": "x"},
                    {"type": "record", "name": "Elasticsearch", "data": "x"},
                ],
            }
        }
    }

    doc = drop_unfiltered_cql2_operations(_items("catalogue"), config)

    assert "post" in doc["paths"]["/collections/catalogue/items"]
