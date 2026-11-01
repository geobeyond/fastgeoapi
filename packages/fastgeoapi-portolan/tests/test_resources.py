"""From the collections of a catalog to pygeoapi resources."""

from __future__ import annotations

import json

import pytest
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer

import fastgeoapi_portolan.resources as resources_module
from fastgeoapi_portolan.catalog.testing import PORTOLAN
from fastgeoapi_portolan.handlers import IngestOptions, Refusal
from fastgeoapi_portolan.reader import (
    Catalog,
    Collection,
    Finding,
    NonconformingDocument,
    SkippedDocument,
)
from fastgeoapi_portolan.resources import DuplicateCollectionIdError, build

PARQUET = "application/vnd.apache.parquet"
COG = "image/tiff; application=geotiff; profile=cloud-optimized"
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


@pytest.fixture
def base(tmp_path):
    return tmp_path.resolve()


def _document(identifier, **fields):
    document = {
        "type": "Collection",
        "id": identifier,
        "title": identifier.capitalize(),
        "description": f"The {identifier} collection.",
        "keywords": ["transport"],
        "license": "CC-BY-4.0",
        "extent": {
            "spatial": {"bbox": [[12.3, 41.8, 12.6, 42.0]]},
            "temporal": {"interval": [["2026-01-01T00:00:00Z", None]]},
        },
        "table:columns": [{"name": "id"}, {"name": "geometry"}],
        "links": [],
        "assets": {"data": {"href": f"./{identifier}.parquet", "type": PARQUET, "roles": ["data"]}},
    }
    document.update(fields)
    return document


def _collection(base, document):
    href = str(base / document["id"] / "collection.json")
    return Collection(document["id"], href, document, (), PORTOLAN)


def _catalog(base, *collections, nonconforming=(), skipped=()):
    return Catalog(
        root=str(base / "catalog.json"),
        portolan_schema=PORTOLAN,
        collections=tuple(collections),
        nonconforming=tuple(nonconforming),
        skipped=tuple(skipped),
        warnings=(),
        validated=True,
    )


def _archive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
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


@pytest.mark.asyncio
async def test_metadata_and_extents_follow_the_collection(base):
    built, skipped = await build(
        _catalog(base, _collection(base, _document("roads"))), IngestOptions()
    )

    (roads,) = built
    resource = roads.resource
    assert roads.id == "roads"
    assert skipped == []
    assert resource["type"] == "collection"
    assert (resource["title"], resource["description"], resource["keywords"]) == (
        "Roads",
        "The roads collection.",
        ["transport"],
    )
    assert resource["extents"] == {
        "spatial": {"bbox": [12.3, 41.8, 12.6, 42.0], "crs": CRS84},
        "temporal": {"begin": "2026-01-01T00:00:00Z"},
    }


@pytest.mark.asyncio
async def test_license_readme_and_source_become_links(base):
    links = [
        {"rel": "describedby", "href": "./README.md", "type": "text/markdown"},
        {
            "rel": "via",
            "href": "https://example.org/roads",
            "type": "text/html",
            "title": "Roads office",
        },
        {"rel": "child", "href": "./x.json", "type": "application/json"},
    ]
    document = _document("roads", links=links)

    (roads,), _ = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert roads.resource["links"] == [
        {
            "type": "text/markdown",
            "rel": "describedby",
            "title": "README",
            "href": str(base / "roads" / "README.md"),
        },
        {
            "type": "text/html",
            "rel": "via",
            "title": "Roads office",
            "href": "https://example.org/roads",
        },
        {
            "type": "text/html",
            "rel": "license",
            "title": "CC-BY-4.0",
            "href": "https://spdx.org/licenses/CC-BY-4.0.html",
        },
    ]


@pytest.mark.asyncio
async def test_a_license_link_of_the_collection_wins_over_the_identifier(base):
    link = {
        "rel": "license",
        "href": "https://example.org/terms",
        "type": "text/html",
        "title": "Terms",
    }
    # The identifier would give an SPDX link; the collection's own link wins.
    document = _document("roads", links=[link])

    (roads,), _ = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert [entry for entry in roads.resource["links"] if entry["rel"] == "license"] == [
        {
            "type": "text/html",
            "rel": "license",
            "title": "Terms",
            "href": "https://example.org/terms",
        }
    ]


@pytest.mark.asyncio
async def test_a_collection_with_both_assets_has_both_providers(base):
    _archive(base / "roads" / "roads.pmtiles")
    assets = {
        "data": {"href": "./roads.parquet", "type": PARQUET, "roles": ["data"]},
        "tiles": {
            "href": "./roads.pmtiles",
            "type": "application/vnd.pmtiles",
            "roles": ["visual"],
        },
    }

    (roads,), _ = await build(
        _catalog(base, _collection(base, _document("roads", assets=assets))), IngestOptions()
    )

    assert [provider["type"] for provider in roads.resource["providers"]] == ["feature", "tile"]
    assert "data: collection asset" in roads.choices
    assert "data: visual asset" in roads.choices


@pytest.mark.asyncio
async def test_a_refused_provider_is_named_when_another_one_serves(base):
    _archive(base / "roads" / "roads.pmtiles")
    assets = {
        "data": {"href": "./roads.parquet", "type": PARQUET, "roles": ["data"]},
        "tiles": {
            "href": "./roads.pmtiles",
            "type": "application/vnd.pmtiles",
            "roles": ["visual"],
        },
    }
    document = _document("roads", assets=assets, **{"table:columns": [{"name": "name"}]})

    (roads,), skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert [provider["type"] for provider in roads.resource["providers"]] == ["tile"]
    assert any(
        choice.startswith("geoparquet left out: no column to use as id") for choice in roads.choices
    )
    assert skipped == []


@pytest.mark.asyncio
async def test_a_collection_no_handler_serves_is_skipped(base):
    document = _document(
        "roads", assets={"data": {"href": "./roads.tif", "type": COG, "roles": ["data"]}}
    )

    built, skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert built == []
    assert skipped == [SkippedDocument("roads", f"format not handled yet: {COG}")]


@pytest.mark.asyncio
async def test_a_collection_every_handler_refuses_is_skipped_with_the_reasons(base):
    document = _document("roads", **{"table:columns": [{"name": "name"}]})

    built, skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert built == []
    (entry,) = skipped
    assert entry.collection == "roads"
    assert entry.reason.startswith("no column to use as id")


@pytest.mark.asyncio
async def test_two_collections_with_one_id_stop_before_anything_is_built(base):
    first = _collection(base, _document("roads"))
    second = Collection(
        "roads", str(base / "other" / "collection.json"), _document("roads"), (), PORTOLAN
    )

    with pytest.raises(DuplicateCollectionIdError, match=r"--prefix.*--collection"):
        await build(_catalog(base, first, second), IngestOptions())


@pytest.mark.asyncio
async def test_the_prefix_goes_before_every_id(base):
    catalog = _catalog(
        base, _collection(base, _document("roads")), _collection(base, _document("rivers"))
    )

    built, _ = await build(catalog, IngestOptions(), prefix="overture-")

    assert [entry.id for entry in built] == ["overture-roads", "overture-rivers"]
    assert [entry.resource["ingest"]["collection"] for entry in built] == ["roads", "rivers"]


@pytest.mark.asyncio
async def test_provenance_names_the_root_catalog(base):
    (roads,), _ = await build(
        _catalog(base, _collection(base, _document("roads"))), IngestOptions()
    )

    assert roads.resource["ingest"] == {
        "from": "portolan",
        "catalog": str(base / "catalog.json"),
        "collection": "roads",
        "schema": PORTOLAN,
    }


@pytest.mark.asyncio
async def test_a_plain_stac_catalog_leaves_the_schema_out_of_the_provenance(base):
    catalog = _catalog(base, _collection(base, _document("roads")))
    plain = Catalog(catalog.root, None, catalog.collections, (), (), (), True)

    (roads,), _ = await build(plain, IngestOptions())

    assert "schema" not in roads.resource["ingest"]


@pytest.mark.asyncio
async def test_a_collection_without_a_title_is_skipped_with_the_reason(base):
    document = _document("roads")
    del document["title"]

    built, skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert built == []
    assert skipped == [SkippedDocument("roads", "the collection has no title")]


@pytest.mark.parametrize(
    ("fields", "where"),
    [
        ({"title": "Roads ${HOME}"}, "title"),
        ({"description": "Tiles at {z}/${x}/{y}."}, "description"),
        ({"keywords": ["transport", "${AWS_SECRET_ACCESS_KEY}"]}, "keywords[1]"),
        ({"table:primary_key": ["${USER}"]}, "providers[0].id_field"),
        (
            {"links": [{"rel": "license", "href": "https://example.org/${TOKEN:-x}"}]},
            "links[0].href",
        ),
    ],
)
@pytest.mark.asyncio
async def test_catalog_text_that_the_configuration_would_read_as_a_variable_is_skipped(
    base, fields, where
):
    """pygeoapi replaces a ${NAME} in the configuration with the variable of the server."""
    document = _document("roads", **fields)

    built, skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert built == []
    assert skipped == [
        SkippedDocument(
            "roads", f"{where} holds '${{', which the configuration reads as a variable"
        )
    ]


@pytest.mark.asyncio
async def test_a_profile_url_that_holds_a_variable_is_skipped(base):
    catalog = _catalog(base, _collection(base, _document("roads")))
    catalog = Catalog(
        **{
            **catalog.__dict__,
            "portolan_schema": "https://schemas.portolan-sdi.org/portolan/${X}/schema.json",
        }
    )

    built, skipped = await build(catalog, IngestOptions())

    assert built == []
    assert (
        skipped[0].reason == "ingest.schema holds '${', which the configuration reads as a variable"
    )


@pytest.mark.asyncio
async def test_a_collection_id_that_holds_a_variable_is_skipped(base):
    document = _document("roads", id="${ROADS}")

    built, skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert built == []
    assert skipped[0].reason == "id holds '${', which the configuration reads as a variable"


@pytest.mark.asyncio
async def test_a_style_named_with_a_variable_is_skipped(base):
    _archive(base / "roads" / "roads.pmtiles")
    style = {
        "version": 8,
        "sources": {"roads": {"type": "vector", "url": "pmtiles://./roads.pmtiles"}},
        "layers": [],
    }
    (base / "roads" / "night.json").write_text(json.dumps(style))
    assets = {
        "tiles": {
            "href": "./roads.pmtiles",
            "type": "application/vnd.pmtiles",
            "roles": ["visual"],
        },
        "night": {
            "href": "./night.json",
            "type": "application/json",
            "roles": ["style"],
            "title": "${NIGHT}",
        },
    }
    document = _document("roads", assets=assets)

    built, skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert built == []
    assert skipped[0].reason == (
        "providers[0].options.styles.${NIGHT} holds '${', which the configuration reads as a variable"
    )


@pytest.mark.asyncio
async def test_a_style_named_store_options_is_still_checked_for_variables(base):
    """The check leaves out the store options of the provider, and nothing else with that name."""
    _archive(base / "roads" / "roads.pmtiles")
    style = {
        "version": 8,
        "sources": {"roads": {"type": "vector", "url": "pmtiles://./roads.pmtiles"}},
        "layers": [],
    }
    (base / "roads" / "${SECRET}.json").write_text(json.dumps(style))
    assets = {
        "tiles": {
            "href": "./roads.pmtiles",
            "type": "application/vnd.pmtiles",
            "roles": ["visual"],
        },
        "night": {
            "href": "./${SECRET}.json",
            "type": "application/json",
            "roles": ["style"],
            "title": "store_options",
        },
    }
    document = _document("roads", assets=assets)

    built, skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert built == []
    assert skipped[0].reason == (
        "providers[0].options.styles.store_options holds '${',"
        " which the configuration reads as a variable"
    )


@pytest.mark.asyncio
async def test_a_provider_refused_for_now_leaves_the_whole_collection_as_it_is(base, monkeypatch):
    async def unavailable(collection, ingest_options):
        return Refusal("the archive could not be read: HTTP 503", transient=True)

    handlers = dict(resources_module.HANDLERS)
    handlers["pmtiles"] = unavailable
    monkeypatch.setattr(resources_module, "HANDLERS", tuple(handlers.items()))

    built, skipped = await build(
        _catalog(base, _collection(base, _document("roads"))), IngestOptions()
    )

    assert built == []
    assert skipped == [
        SkippedDocument(
            "roads",
            "pmtiles: the archive could not be read: HTTP 503; nothing changes until it can be read",
        )
    ]


@pytest.mark.asyncio
async def test_variables_in_the_store_options_given_by_the_user_are_kept(base):
    options = IngestOptions(store_options={"endpoint": "${S3_ENDPOINT}"})

    (roads,), _ = await build(_catalog(base, _collection(base, _document("roads"))), options)

    assert roads.resource["providers"][0]["store_options"] == {"endpoint": "${S3_ENDPOINT}"}


@pytest.mark.asyncio
async def test_nonconforming_collections_are_reported_as_skipped(base):
    findings = (
        Finding("/stac_extensions", "[] should be non-empty", PORTOLAN),
        Finding("", "'title' is a required property", PORTOLAN),
    )
    rejected = (
        NonconformingDocument(
            str(base / "roads" / "collection.json"), "Collection", {"id": "roads"}, findings
        ),
        NonconformingDocument(
            str(base / "rivers" / "collection.json"), "Collection", {"id": "rivers"}, findings[1:]
        ),
        NonconformingDocument(
            str(base / "data" / "catalog.json"), "Catalog", {"id": "data"}, findings[1:]
        ),
    )

    _, skipped = await build(_catalog(base, nonconforming=rejected), IngestOptions())

    assert skipped == [
        SkippedDocument(
            "roads",
            f"does not conform to {PORTOLAN}: /stac_extensions [] should be non-empty (+1 more)",
        ),
        SkippedDocument(
            "rivers", f"does not conform to {PORTOLAN}: 'title' is a required property"
        ),
    ]


@pytest.mark.asyncio
async def test_documents_the_walk_skipped_are_reported_too(base):
    unread = SkippedDocument(
        str(base / "gone" / "collection.json"), "the document could not be read: it does not exist"
    )

    _, skipped = await build(_catalog(base, skipped=[unread]), IngestOptions())

    assert skipped == [unread]


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (lambda document: document.pop("description"), "the collection has no description"),
        (lambda document: document.pop("extent"), "the collection has no spatial extent"),
    ],
)
@pytest.mark.asyncio
async def test_a_collection_without_what_pygeoapi_needs_is_skipped(base, change, reason):
    document = _document("roads")
    change(document)

    built, skipped = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert built == []
    assert skipped == [SkippedDocument("roads", reason)]


@pytest.mark.asyncio
async def test_a_license_that_is_not_an_spdx_identifier_gives_no_link(base):
    document = _document("roads", license="proprietary")

    (roads,), _ = await build(_catalog(base, _collection(base, document)), IngestOptions())

    assert "links" not in roads.resource


@pytest.mark.asyncio
async def test_a_collection_without_data_says_so(base):
    built, skipped = await build(
        _catalog(base, _collection(base, _document("roads", assets={}))), IngestOptions()
    )

    assert built == []
    assert skipped == [SkippedDocument("roads", "format not handled yet: no data or visual asset")]


@pytest.mark.asyncio
async def test_a_collection_whose_items_cannot_be_read_is_skipped(base):
    document = _document("roads", assets={})
    href = str(base / "roads" / "collection.json")
    gone = str(base / "roads" / "items" / "part-0.json")
    collection = Collection("roads", href, document, (gone,), PORTOLAN)

    built, skipped = await build(_catalog(base, collection), IngestOptions())

    assert built == []
    assert skipped == [SkippedDocument("roads", "the items could not be read: it does not exist")]
