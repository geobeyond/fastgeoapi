"""Merging ingested resources into a configuration document someone already keeps."""

from __future__ import annotations

import copy

import pytest
from ruamel.yaml import YAML

from fastgeoapi_portolan.geoparquet import PROVIDER as GEOPARQUET
from fastgeoapi_portolan.merge import merge, render
from fastgeoapi_portolan.reader import SkippedDocument
from fastgeoapi_portolan.resources import IngestedResource

CATALOG = "https://example.org/cat/catalog.json"
PORTOLAN = "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json"

DOCUMENT = """\
# The server of the example.
server:
  bind:
    host: ${HOST}
    port: ${PORT}
  url: "${PYGEOAPI_BASEURL}"
  mimetype: 'application/json; charset=UTF-8'
  languages:
    - en-US

logging:
  level: ERROR

resources:
  # Lakes, written by hand.
  lakes:
    type: collection
    title: Large lakes
    description:
      The largest lakes of the world, a dataset kept by hand
      in this file
    keywords:
      - lakes
    extents:
      spatial:
        bbox: [-180, -90, 180, 90]
        crs: http://www.opengis.net/def/crs/OGC/1.3/CRS84
      temporal:
        begin: 2011-11-11T11:11:11Z
        end: null
    providers:
      - type: feature
        name: GeoJSON
        data: tests/data/ne_110m_lakes.geojson
        id_field: id
  hello-world:
    type: process
    processor:
      name: HelloWorld
"""


def _built(collection, *, catalog=CATALOG, title=None, resource_id=None):
    resource = {
        "type": "collection",
        "title": title or collection.capitalize(),
        "description": f"The {collection} collection.",
        "keywords": ["transport"],
        "extents": {
            "spatial": {
                "bbox": [12.3, 41.8, 12.6, 42.0],
                "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            }
        },
        "providers": [
            {
                "type": "feature",
                "name": GEOPARQUET,
                "data": f"s3://bucket/{collection}.parquet",
                "id_field": "id",
                "geometry_column": "geometry",
            }
        ],
        "ingest": {
            "from": "portolan",
            "catalog": catalog,
            "collection": collection,
            "schema": PORTOLAN,
        },
    }
    return IngestedResource(resource_id or collection, resource, ())


def _resources(text):
    return YAML(typ="safe").load(text)["resources"]


def test_the_document_is_byte_identical_outside_resources():
    merged = merge(DOCUMENT, [_built("roads")], catalog=CATALOG, selected=None, prune=False)

    assert merged.text.startswith(DOCUMENT)
    assert merged.text[len(DOCUMENT) :].startswith("  roads:\n")


def test_new_collections_are_added_at_the_end_of_resources():
    merged = merge(
        DOCUMENT, [_built("roads"), _built("rivers")], catalog=CATALOG, selected=None, prune=False
    )

    assert list(_resources(merged.text)) == ["lakes", "hello-world", "roads", "rivers"]
    assert (merged.added, merged.updated, merged.skipped) == (["roads", "rivers"], [], [])


def test_an_ingested_resource_is_updated_key_by_key():
    first = merge(DOCUMENT, [_built("roads")], catalog=CATALOG, selected=None, prune=False)
    by_hand = first.text.replace("  roads:\n", "  roads:\n    view:\n      zoom: 9\n")

    second = merge(
        by_hand, [_built("roads", title="Main roads")], catalog=CATALOG, selected=None, prune=False
    )

    roads = _resources(second.text)["roads"]
    assert roads["title"] == "Main roads"
    assert roads["view"] == {"zoom": 9}
    assert second.updated == ["roads"]
    assert second.text.startswith(DOCUMENT)


def test_providers_other_than_ours_are_kept():
    first = merge(DOCUMENT, [_built("roads")], catalog=CATALOG, selected=None, prune=False)
    hand_map = (
        "      - type: map\n"
        "        name: app.provider.maplibre.MapLibreProvider\n"
        "        data: https://example.org/styles/roads.json\n"
    )
    marker = "    ingest:\n"
    with_map = first.text.replace(marker, hand_map + marker, 1)
    rebuilt = _built("roads")
    rebuilt.resource["providers"][0]["data"] = "s3://bucket/roads-2.parquet"

    second = merge(with_map, [rebuilt], catalog=CATALOG, selected=None, prune=False)

    providers = _resources(second.text)["roads"]["providers"]
    assert [provider["name"] for provider in providers] == [
        GEOPARQUET,
        "app.provider.maplibre.MapLibreProvider",
    ]
    assert providers[0]["data"] == "s3://bucket/roads-2.parquet"


def test_a_hand_written_resource_with_the_same_id_is_left_alone():
    merged = merge(DOCUMENT, [_built("lakes")], catalog=CATALOG, selected=None, prune=False)

    assert merged.text == DOCUMENT
    assert merged.skipped == [
        SkippedDocument(
            "lakes", "the configuration has a resource lakes written by hand: left alone"
        )
    ]


def test_a_resource_from_another_catalog_with_the_same_id_is_left_alone():
    other = "https://elsewhere.example.org/catalog.json"
    first = merge(
        DOCUMENT, [_built("roads", catalog=other)], catalog=other, selected=None, prune=False
    )

    second = merge(first.text, [_built("roads")], catalog=CATALOG, selected=None, prune=False)

    assert second.text == first.text
    assert second.skipped == [
        SkippedDocument(
            "roads", f"the resource roads comes from {other}, collection roads: left alone"
        )
    ]


def test_a_second_ingest_of_the_same_catalog_changes_nothing():
    built = [_built("roads"), _built("rivers")]
    first = merge(DOCUMENT, built, catalog=CATALOG, selected=None, prune=False)

    second = merge(first.text, copy.deepcopy(built), catalog=CATALOG, selected=None, prune=False)

    assert second.text == first.text
    assert (second.added, second.updated, second.missing) == ([], [], [])


def test_a_catalog_named_by_its_directory_is_the_same_catalog():
    first = merge(
        DOCUMENT,
        [_built("roads", catalog="https://example.org/cat/")],
        catalog="https://example.org/cat/",
        selected=None,
        prune=False,
    )

    second = merge(
        first.text,
        [_built("roads", title="Main roads")],
        catalog=CATALOG,
        selected=None,
        prune=False,
    )

    assert second.skipped == []
    assert second.updated == ["roads"]


def test_collections_gone_from_the_catalog_are_reported_and_kept():
    first = merge(
        DOCUMENT, [_built("roads"), _built("rivers")], catalog=CATALOG, selected=None, prune=False
    )

    second = merge(first.text, [_built("roads")], catalog=CATALOG, selected=None, prune=False)

    assert second.missing == ["rivers"]
    assert second.pruned == []
    assert "rivers" in _resources(second.text)


def test_a_collection_the_catalog_still_lists_is_not_missing():
    first = merge(
        DOCUMENT, [_built("roads"), _built("rivers")], catalog=CATALOG, selected=None, prune=False
    )

    second = merge(
        first.text,
        [_built("roads")],
        catalog=CATALOG,
        selected=None,
        prune=True,
        still_listed=frozenset({"rivers"}),
    )

    assert (second.missing, second.pruned) == ([], [])
    assert "rivers" in _resources(second.text)


def test_prune_removes_only_this_catalogs_resources():
    other = "https://elsewhere.example.org/catalog.json"
    first = merge(
        DOCUMENT, [_built("roads"), _built("rivers")], catalog=CATALOG, selected=None, prune=False
    )
    second = merge(
        first.text, [_built("parks", catalog=other)], catalog=other, selected=None, prune=False
    )

    third = merge(second.text, [_built("roads")], catalog=CATALOG, selected=None, prune=True)

    assert third.pruned == ["rivers"]
    assert list(_resources(third.text)) == ["lakes", "hello-world", "roads", "parks"]
    assert third.text.startswith(DOCUMENT)


def test_prune_leaves_the_collections_not_selected():
    first = merge(
        DOCUMENT, [_built("roads"), _built("rivers")], catalog=CATALOG, selected=None, prune=False
    )

    second = merge(
        first.text, [_built("roads")], catalog=CATALOG, selected=frozenset({"roads"}), prune=True
    )

    assert (second.missing, second.pruned) == ([], [])
    assert "rivers" in _resources(second.text)


def test_render_prints_only_resources():
    text = render([_built("roads")])

    document = YAML(typ="safe").load(text)
    assert list(document) == ["resources"]
    assert document["resources"]["roads"]["ingest"]["collection"] == "roads"


def test_a_document_without_resources_gets_them_at_the_end():
    document = "server:\n  url: ${PYGEOAPI_BASEURL}\n"

    merged = merge(document, [_built("roads")], catalog=CATALOG, selected=None, prune=False)

    assert merged.text.startswith(document + "resources:\n  roads:\n")
    assert list(_resources(merged.text)) == ["roads"]


@pytest.mark.parametrize("section", ["resources:\n", "resources: {}\n"])
def test_an_empty_resources_section_is_filled(section):
    document = "server:\n  url: ${PYGEOAPI_BASEURL}\n" + section

    merged = merge(document, [_built("roads")], catalog=CATALOG, selected=None, prune=False)

    assert merged.text.startswith("server:\n  url: ${PYGEOAPI_BASEURL}\nresources:\n  roads:\n")
    assert list(_resources(merged.text)) == ["roads"]


def test_a_comment_after_the_resources_stays_last():
    document = DOCUMENT + "\n# The end of the example.\n"

    merged = merge(document, [_built("roads")], catalog=CATALOG, selected=None, prune=False)

    assert merged.text.startswith(DOCUMENT)
    assert merged.text.endswith("\n\n# The end of the example.\n")
    assert "roads" in _resources(merged.text)


def test_the_comment_of_the_next_resource_stays_with_it():
    first = merge(
        DOCUMENT, [_built("roads"), _built("rivers")], catalog=CATALOG, selected=None, prune=False
    )
    commented = first.text.replace("  rivers:\n", "  # Rivers, from the catalog.\n  rivers:\n")

    second = merge(
        commented,
        [_built("roads", title="Main roads"), _built("rivers")],
        catalog=CATALOG,
        selected=None,
        prune=False,
    )

    assert second.updated == ["roads"]
    assert "  # Rivers, from the catalog.\n  rivers:\n" in second.text


def test_a_null_is_written_as_null():
    roads = _built("roads")
    roads.resource["extents"]["temporal"] = {"begin": "2026-01-01T00:00:00Z", "end": None}

    assert "        end: null\n" in render([roads])
