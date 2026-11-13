"""Tool schemas as an MCP client reads them.

Clients check a tool's result against its output schema and build the
arguments from its input schema. Two of the schemas generated from our
OpenAPI document did not match what the server does, and the Claude
connector ran into all of these on the demo:

- ``getConformanceDeclaration`` carried the landing page schema, which
  requires ``links``, so every correct answer was rejected.
- ``executeHello_worldJob`` described ``inputs`` and ``outputs`` without
  a type, because the OGC ``execute.yaml`` omits it. The client sent
  ``inputs`` as a JSON string and pygeoapi answered 400.
- ``getLakesFeatures`` with ``skipGeometry=true`` returns features whose
  ``geometry`` is ``null``, which the OGC feature schema does not allow.
- ``getCQL2LakesFeatures`` accepted a CQL2 filter that the GeoJSON
  provider ignores, and returned the whole collection.
"""

import pytest
from fastmcp import Client


async def _tools(mcp_main) -> dict:
    async with Client(mcp_main.mcp) as client:
        return {tool.name: tool for tool in await client.list_tools()}


@pytest.mark.asyncio
async def test_the_conformance_tool_expects_a_conformance_declaration(mcp_main):
    schema = (await _tools(mcp_main))["getConformanceDeclaration"].outputSchema

    assert "conformsTo" in schema.get("required", [])
    assert "links" not in schema.get("required", [])


@pytest.mark.asyncio
async def test_the_conformance_tool_answer_passes_its_own_schema(mcp_main):
    async with Client(mcp_main.mcp) as client:
        result = await client.call_tool("getConformanceDeclaration", {})

    assert not result.is_error
    assert result.structured_content["conformsTo"]


@pytest.mark.asyncio
async def test_the_execute_tool_declares_inputs_and_outputs_as_objects(mcp_main):
    properties = (await _tools(mcp_main))["executeHello_worldJob"].inputSchema["properties"]

    assert properties["inputs"].get("type") == "object"
    assert properties["outputs"].get("type") == "object"


@pytest.mark.asyncio
async def test_features_without_geometry_pass_the_tool_schema(mcp_main):
    async with Client(mcp_main.mcp) as client:
        result = await client.call_tool("getLakesFeatures", {"limit": 1, "skipGeometry": True})

    assert not result.is_error
    assert result.structured_content["features"][0]["geometry"] is None


@pytest.mark.asyncio
async def test_no_cql2_tool_for_a_provider_that_ignores_the_filter(mcp_main):
    tools = await _tools(mcp_main)

    assert "getCQL2LakesFeatures" not in tools
    assert "getLakesFeatures" in tools
