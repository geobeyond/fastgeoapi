"""Binary tiles are not tools; their tilesets and metadata are (ADR-0011, decision 8).

Two checks, deliberately apart: the exclusion pattern matches the path
template pygeoapi really generates (no network: the raw document is
enough for its paths), and FastMCP drops that operation while keeping
the tileset one (a hand-written document, so nothing external needs
resolving).
"""

import re

import httpx2
import pytest
from fastmcp import FastMCP

from app.mcp.route_maps import TILE_DATA_PATTERN, openapi_route_maps
from app.pygeoapi.factory import build_openapi
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_pmtiles_route import _provider
from tests.test_tiles_async_route import _collection, _config

TILE_PATH = "/collections/places/tiles/{tileMatrixSetId}/{tileMatrix}/{tileRow}/{tileCol}"


def _path_parameter(name: str) -> dict:
    return {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}


def test_the_pattern_matches_the_path_pygeoapi_generates(tmp_path):
    path = write_archive(tmp_path / "places.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})
    openapi = build_openapi(_config({"places": _collection("Places", [_provider(path)])}))
    tile_paths = [p for p in openapi["paths"] if re.match(TILE_DATA_PATTERN, p)]
    assert tile_paths == [TILE_PATH]
    assert not re.match(TILE_DATA_PATTERN, "/collections/places/tiles")


@pytest.mark.asyncio
async def test_the_tile_operation_is_excluded_and_the_tilesets_one_kept():
    document = {
        "openapi": "3.0.2",
        "info": {"title": "test", "version": "1"},
        "paths": {
            "/collections/places/tiles": {
                "get": {
                    "operationId": "describePlaces.collection.vector.getTileSetsList",
                    "responses": {"200": {"description": "ok"}},
                }
            },
            TILE_PATH: {
                "get": {
                    "operationId": "getPlaces.collection.vector.getTile",
                    "parameters": [
                        _path_parameter(name)
                        for name in ("tileMatrixSetId", "tileMatrix", "tileRow", "tileCol")
                    ],
                    "responses": {"200": {"description": "a tile"}},
                }
            },
        },
    }
    server = FastMCP.from_openapi(
        openapi_spec=document,
        client=httpx2.AsyncClient(base_url="http://example.invalid"),
        name="test",
        route_maps=openapi_route_maps(),
    )
    names = {tool.name for tool in await server.list_tools()}
    assert any("TileSetsList" in name for name in names), names
    assert not any(name.endswith("getTile") for name in names), names
