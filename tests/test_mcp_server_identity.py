"""What the MCP server says about itself when a client connects.

A client shows the server's name, version and website, and hands its
instructions to the model before any tool is called. The server card
already publishes the fastgeoapi version and the API address; the
handshake reported FastMCP's own version and no instructions.
"""

import pytest
from fastmcp import Client

from app.mcp.card import fastgeoapi_version


@pytest.mark.asyncio
async def test_the_server_reports_the_fastgeoapi_version(mcp_main):
    async with Client(mcp_main.mcp) as client:
        version = client.server_info.version

    assert version == fastgeoapi_version()


@pytest.mark.asyncio
async def test_the_website_is_the_api_the_server_card_names(mcp_main):
    async with Client(mcp_main.mcp) as client:
        website = client.server_info.website_url

    assert website == f"{mcp_main._public_base_url().rstrip('/')}{mcp_main.cfg.FASTGEOAPI_CONTEXT}"


@pytest.mark.asyncio
async def test_the_instructions_name_tools_the_server_has(mcp_main):
    async with Client(mcp_main.mcp) as client:
        instructions = client.instructions or ""
        tools = {tool.name for tool in await client.list_tools()}

    for name in ("getCollections", "getProcesses"):
        assert name in instructions
        assert name in tools
