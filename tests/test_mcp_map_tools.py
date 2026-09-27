"""get<Collection>Map: the map of a bbox, handed to the client as an image."""

import base64

import pytest

from tests.maps_fixtures import map_provider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    archive = write_archive(
        tmp_path_factory.mktemp("mcp-maps") / "roads.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "roads", "vector_layers": [{"id": "roads"}]},
    )
    config = _config({"lazio-roads": _collection("Lazio roads", [map_provider(archive)])})
    document = build_openapi(config)
    return document, build_pygeoapi_subapp(config, document)


async def _client_tools(served):
    import httpx2
    from fastmcp import Client, FastMCP

    from app.mcp.tools import refresh_tools

    document, subapp = served
    api = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=subapp), base_url="http://mcp-internal"
    )
    server = FastMCP(name="test")
    refresh_tools(server, document, client=api)
    return api, Client(server)


@pytest.mark.asyncio
async def test_the_map_tool_returns_an_image(served):
    api, client = await _client_tools(served)
    async with api, client:
        result = await client.call_tool(
            "getLazio_roadsMap", {"bbox": [12.4, 41.8, 12.6, 42.0], "width": 64, "height": 64}
        )

    (image,) = result.content
    assert image.type == "image"
    assert image.mime_type == "image/png"
    assert base64.b64decode(image.data).startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_the_generated_map_operation_is_not_a_tool(served):
    api, client = await _client_tools(served)
    async with api, client:
        names = {tool.name for tool in await client.list_tools()}

    assert "getLazio_roadsMap" in names
    assert not {name for name in names if name.startswith("getMap")}


@pytest.mark.asyncio
async def test_the_map_tool_is_read_only_and_titled(served):
    api, client = await _client_tools(served)
    async with api, client:
        (tool,) = [t for t in await client.list_tools() if t.name == "getLazio_roadsMap"]

    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False
    assert tool.title == "Map of Lazio roads"
    assert tool.input_schema["properties"]["width"]["maximum"] == 1024


@pytest.mark.asyncio
async def test_a_server_error_reaches_the_client_as_a_tool_error(served):
    api, client = await _client_tools(served)
    async with api, client:
        result = await client.call_tool(
            "getLazio_roadsMap",
            {"bbox": [12.4, 41.8, 12.6, 42.0], "style": "missing"},
            raise_on_error=False,
        )

    assert result.is_error
    assert "not found" in result.content[0].text


def test_the_instructions_name_the_map_tool():
    from app.mcp.instructions import SERVER_INSTRUCTIONS

    assert "get<Collection>Map " in SERVER_INSTRUCTIONS
