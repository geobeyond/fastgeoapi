"""The tileset list is described by the response OGC API - Tiles gives it.

pygeoapi answers ``GET /collections/{id}/tiles`` with a TileSetsList,
``{links, tilesets}``, but its document points the 200 at a local schema
from an earlier draft that requires ``tileMatrixSetLinks``. No answer has
that field, so a client that checks results against the tool schema
drops every one of them. The Claude connector did, on the demo.
"""

from __future__ import annotations

import pytest

from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_pmtiles_route import _provider
from tests.test_tiles_async_route import _collection, _config


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    """The OpenAPI document and the pygeoapi sub-app of one tile collection."""
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    archive = write_archive(
        tmp_path_factory.mktemp("tilesets") / "places.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={
            "name": "Places",
            "vector_layers": [{"id": "place", "minzoom": 0, "maxzoom": 2}],
        },
    )
    config = _config({"places": _collection("Places", [_provider(archive)])})
    document = build_openapi(config)
    return document, build_pygeoapi_subapp(config, document)


def test_the_tileset_list_refers_to_the_ogc_response(served):
    document, _ = served

    response = document["paths"]["/collections/places/tiles"]["get"]["responses"]["200"]

    assert response["$ref"].endswith("/responses/tiles-core/rTileSetsList.yaml")


def test_the_draft_components_are_gone(served):
    document, _ = served
    components = document["components"]

    assert "Tiles" not in components["responses"]
    assert not {"tiles", "tilematrixsetlink"} & set(components["schemas"])


@pytest.mark.asyncio
async def test_the_tileset_list_tool_accepts_what_the_server_answers(served):
    """End to end: the client validates the answer against the tool schema."""
    import httpx2
    from fastmcp import Client, FastMCP

    from app.mcp.tools import refresh_tools

    document, subapp = served
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=subapp), base_url="http://mcp-internal"
    ) as api:
        server = FastMCP(name="test")
        refresh_tools(server, document, client=api)
        async with Client(server) as client:
            result = await client.call_tool("getPlacesTileSets", {})

    assert result.structured_content["tilesets"]
