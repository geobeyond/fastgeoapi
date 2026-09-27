"""A tileset asked for with no format is answered in JSON.

pygeoapi hands the raw requested format to the tile provider, which
calls ``.upper()`` on it (``api/tiles.py:321`` and
``provider/base_mvt.py:205``, 0.24). A request with no ``f`` and an
``Accept`` pygeoapi does not map to a format, such as httpx's ``*/*``,
has no format at all, and the server answered 500. The MCP tools send
exactly that request, so on the demo the tool of a single tileset failed
with ``'NoneType' object has no attribute 'upper'``.
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
        tmp_path_factory.mktemp("tileset") / "places.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={
            "name": "Places",
            "vector_layers": [{"id": "place", "minzoom": 0, "maxzoom": 2}],
        },
    )
    config = _config({"places": _collection("Places", [_provider(archive)])})
    document = build_openapi(config)
    return document, build_pygeoapi_subapp(config, document)


@pytest.mark.parametrize(
    "path",
    [
        "/collections/places/tiles/WebMercatorQuad",
        "/collections/places/tiles/WebMercatorQuad/metadata",
    ],
)
def test_a_tileset_with_no_format_is_json(served, path):
    from starlette.testclient import TestClient

    _, subapp = served
    response = TestClient(subapp, raise_server_exceptions=False).get(
        path, headers={"Accept": "*/*"}
    )

    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["tileMatrixSetURI"].endswith("/WebMercatorQuad")


@pytest.mark.asyncio
async def test_the_tileset_tool_answers_without_a_format(served):
    """End to end: the tool sends no ``f``, and the client checks the schema."""
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
            result = await client.call_tool(
                "getPlacesTileSet", {"tileMatrixSetId": "WebMercatorQuad"}
            )

    assert result.structured_content["dataType"] == "vector"
