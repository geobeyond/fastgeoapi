"""Tool schemas as an MCP client reads them.

Clients check a tool's result against its output schema and build the
arguments from its input schema. Two of the schemas generated from our
OpenAPI document did not match what the server does, and the Claude
connector ran into both on the demo:

- ``getConformanceDeclaration`` carried the landing page schema, which
  requires ``links``, so every correct answer was rejected.
- ``executeHello_worldJob`` described ``inputs`` and ``outputs`` without
  a type, because the OGC ``execute.yaml`` omits it. The client sent
  ``inputs`` as a JSON string and pygeoapi answered 400.
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
