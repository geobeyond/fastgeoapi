"""Tool names: FastMCP cuts them at 56 characters.

On the demo the list of the Overture tilesets and the single tileset
shared their first 56 characters, because pygeoapi puts the collection
id in front of the OGC API - Tiles operation ids. FastMCP told them
apart only by adding ``_2`` to the second.
"""

import copy
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest import mock

import httpx2
import pytest
import yaml
from fastmcp import FastMCP
from loguru import logger

from app.mcp.names import MAX_NAME_LENGTH, tool_names
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_pmtiles_route import _provider
from tests.test_tiles_async_route import _collection

LIST = "describeOverture-places-tiles.collection.vector.getTileSetsList"
ONE = "describeOverture-places-tiles.collection.vector.getTileSet"
TILE = "getOverture-places-tiles.collection.vector.getTile"
TILE_PATH = (
    "/collections/overture-places-tiles/tiles/{tileMatrixSetId}/{tileMatrix}/{tileRow}/{tileCol}"
)


def _document(*operations: tuple[str, str]) -> dict:
    """A minimal OpenAPI document with one GET per (path, operationId)."""
    return {
        "openapi": "3.0.2",
        "info": {"title": "test", "version": "1"},
        "paths": {
            path: {"get": {"operationId": op, "responses": {"200": {"description": "ok"}}}}
            for path, op in operations
        },
    }


@pytest.fixture
def warnings() -> Iterator[list[str]]:
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(sink)


def test_the_tileset_list_is_named_like_a_feature_list():
    names = tool_names(_document(("/collections/overture-places-tiles/tiles", LIST)))

    assert names == {LIST: "getOverture-places-tilesTileSets"}


def test_one_tileset_is_named_like_one_feature():
    names = tool_names(
        _document(("/collections/overture-places-tiles/tiles/{tileMatrixSetId}", ONE))
    )

    assert names == {ONE: "getOverture-places-tilesTileSet"}


def test_the_tile_type_is_dropped_from_the_name():
    operation_id = "describeLakes.collection.map.getTileSetsList"

    assert tool_names(_document(("/collections/lakes/tiles", operation_id))) == {
        operation_id: "getLakesTileSets"
    }


def test_the_other_operations_keep_their_names():
    document = _document(
        ("/collections/lakes/items", "getLakesFeatures"),
        ("/collections/lakes", "describeLakesCollection"),
    )

    assert tool_names(document) == {}


def test_a_name_fastmcp_would_cut_is_logged(warnings):
    operation_id = "getCQL2OrAdd" + "A" * 50 + "Features"

    tool_names(_document(("/collections/a/items", operation_id)))

    assert any(operation_id in message for message in warnings), warnings


def test_the_renamed_tilesets_are_not_logged(warnings):
    tool_names(_document(("/collections/overture-places-tiles/tiles", LIST)))

    assert warnings == []


def test_the_tile_data_operation_is_not_a_tool_and_is_not_logged(warnings):
    long_tile = TILE.replace("Overture", "Overture" * 3)

    tool_names(_document((TILE_PATH, long_tile)))

    assert warnings == []


def test_the_instructions_give_the_tileset_names():
    """The instructions name the tools by pattern, and it must be the one tool_names uses."""
    from app.mcp.instructions import SERVER_INSTRUCTIONS

    pattern = tool_names(
        _document(
            ("/l", "describe<Collection>.collection.vector.getTileSetsList"),
            ("/o", "describe<Collection>.collection.vector.getTileSet"),
        )
    )

    for name in pattern.values():
        assert f"{name} " in SERVER_INSTRUCTIONS, name


@pytest.mark.asyncio
async def test_fastmcp_still_cuts_names_where_we_expect():
    """Drift guard on the FastMCP rule the warning mirrors.

    The limit and the slug come from FastMCP internals it does not
    document (``_generate_default_name``, 4.0.3). If an upgrade moves
    either, the warning stops matching what FastMCP does, and no other
    test would notice.
    """
    from app.mcp.names import _slug

    operation_ids = ["get" + "A" * 60, "getLazio-roads.collection.x", "get  Lakes/--Items"]
    document = _document(*((f"/{i}", op) for i, op in enumerate(operation_ids)))
    async with httpx2.AsyncClient(base_url="http://example.invalid") as client:
        server = FastMCP.from_openapi(openapi_spec=document, client=client, name="test")
        names = sorted(tool.name for tool in await server.list_tools())

    assert names == sorted(_slug(op)[:MAX_NAME_LENGTH] for op in operation_ids)


@pytest.mark.asyncio
async def test_a_refresh_names_the_tilesets():
    from app.mcp.tools import refresh_tools

    async with httpx2.AsyncClient(base_url="http://example.invalid") as client:
        server = FastMCP.from_openapi(openapi_spec=_document(), client=client, name="test")
        refresh_tools(
            server,
            _document(
                ("/collections/overture-places-tiles/tiles", LIST),
                ("/collections/overture-places-tiles/tiles/{tileMatrixSetId}", ONE),
            ),
            client=client,
        )
        names = sorted(tool.name for tool in await server.list_tools())

    assert names == ["getOverture_places_tilesTileSet", "getOverture_places_tilesTileSets"]


def test_the_editor_preview_names_the_tilesets():
    from app.editor.inspect import _mcp_tools

    names = _mcp_tools(_document(("/collections/overture-places-tiles/tiles", LIST)))

    assert names == ["getOverture_places_tilesTileSets"]


@pytest.mark.asyncio
async def test_the_running_server_names_the_tilesets_of_a_long_collection_id(tmp_path):
    """End to end on the demo's collection id, through the startup build."""
    config = yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text())
    archive = write_archive(tmp_path / "places.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})
    changed = copy.deepcopy(config)
    changed["resources"]["overture-places-tiles"] = _collection(
        "Overture places tiles", [_provider(archive)]
    )
    target = tmp_path / "pygeoapi-config.yml"
    target.write_text(yaml.safe_dump(changed))

    env = {
        "ENV_STATE": "dev",
        "HOST": "0.0.0.0",
        "PORT": "5000",
        "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
        "PYGEOAPI_BASEURL": "http://localhost:5000",
        "DEV_PYGEOAPI_CONFIG": str(target),
        "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
        "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
        "FASTGEOAPI_CONTEXT": "/geoapi",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        for key in [k for k in sys.modules if k.startswith("app.")]:
            del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        names = {t.name for t in await main_mod.mcp.list_tools(run_middleware=False)}

    assert {"getOverture_places_tilesTileSets", "getOverture_places_tilesTileSet"} <= names
    assert not [name for name in names if name.endswith("_2")], sorted(names)
