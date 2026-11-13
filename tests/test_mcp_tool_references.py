"""Every reference in a tool schema must resolve inside that schema.

A client checks arguments and results against the tool's own schema,
which carries its definitions under ``$defs``. FastMCP 4.0.3 moved the
references into ``$defs`` everywhere except inside ``prefixItems``, so
the CQL2 tools kept six that pointed at ``#/components/schemas/…``, in a
document the client never sees. FastMCP 4.0.6 rewrites those as well
(PrefectHQ/fastmcp#5131).

The CQL2 operation is written only where the provider filters or the
collection is editable, so here ``lakes`` is made editable.
"""

import httpx2
import pytest
from fastmcp import FastMCP


def _references(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                yield value
            else:
                yield from _references(value)
    elif isinstance(node, list):
        for value in node:
            yield from _references(value)


def _resolves(schema: dict, ref: str) -> bool:
    if not ref.startswith("#/"):
        return False
    node = schema
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


@pytest.mark.asyncio
async def test_every_reference_in_a_tool_schema_resolves_in_that_schema():
    from pygeoapi.util import yaml_load

    from app.mcp.tools import refresh_tools
    from app.pygeoapi.factory import build_openapi

    with open("tests/data/pygeoapi-config.yml") as fh:
        config = yaml_load(fh)
    for provider in config["resources"]["lakes"]["providers"]:
        if provider["type"] == "feature":
            provider["editable"] = True

    async with httpx2.AsyncClient(base_url="http://the-tools-are-not-called") as client:
        server = FastMCP(name="test")
        refresh_tools(server, build_openapi(config), client=client)
        tools = await server.list_tools()

    assert "getCQL2OrAddLakesFeatures" in {tool.name for tool in tools}
    dangling = sorted(
        {
            (tool.name, ref)
            for tool in tools
            for schema in (tool.parameters, tool.output_schema or {})
            for ref in _references(schema)
            if not _resolves(schema, ref)
        }
    )
    assert dangling == []
