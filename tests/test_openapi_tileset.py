"""The tileset a collection serves, and the document that forgot it.

`GET /collections/{collectionId}/tiles/{tileMatrixSetId}` is the tileset
description. pygeoapi routes it (`starlette_app.py`) and answers it —
measured against the demo on 2026-09-16, 200 with the tileset document —
but `api/tiles.py` never writes it into the OpenAPI: it generates the
list at `…/tiles` and the tile data path, and nothing in between.

OGC API - Tiles states it with `shall`: `/req/tileset/description`, "the
tileset endpoint SHALL support negotiation of an application/json
response". So the document understates a server that conforms, and the
MCP tools built from that document have no way to describe a tileset.

Patched here until pygeoapi writes it itself.
"""

from __future__ import annotations

import pytest

from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_pmtiles_route import _provider
from tests.test_tiles_async_route import _collection, _config

TILESET = "/collections/places/tiles/{tileMatrixSetId}"


@pytest.fixture(scope="module")
def document(tmp_path_factory) -> dict:
    from app.pygeoapi.factory import build_openapi

    archive = write_archive(
        tmp_path_factory.mktemp("pmtiles") / "places.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={
            "name": "Places",
            "vector_layers": [{"id": "place", "minzoom": 0, "maxzoom": 2}],
        },
    )
    return build_openapi(_config({"places": _collection("Places", [_provider(archive)])}))


def test_the_tileset_the_server_serves_is_in_the_document(document):
    assert TILESET in document["paths"]


def test_it_is_a_get_carrying_the_tile_matrix_set(document):
    operation = document["paths"][TILESET]["get"]
    referenced = [p.get("$ref", "") for p in operation["parameters"]]

    assert any("tileMatrixSetId" in ref for ref in referenced)


def test_it_belongs_to_its_collection(document):
    """Tags are per collection here, and an unused one gets dropped."""
    assert document["paths"][TILESET]["get"]["tags"] == ["places"]


def test_the_list_beside_it_is_left_as_pygeoapi_wrote_it(document):
    """Only the missing path is added; nothing existing is rewritten."""
    assert "/collections/places/tiles" in document["paths"]
    assert document["paths"]["/collections/places/tiles"]["get"]["operationId"]
