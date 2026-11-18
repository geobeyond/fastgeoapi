"""The skills on the MCP server of fastgeoapi, and the setting that turns them off."""

import os
import sys
from unittest import mock

import pytest

BOOT = {
    "ENV_STATE": "dev",
    "DEV_FASTGEOAPI_WITH_MCP": "true",
    "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
    "DEV_API_KEY_ENABLED": "false",
    "DEV_JWKS_ENABLED": "false",
    "DEV_OPA_ENABLED": "false",
}


@pytest.fixture(name="main_without_skills")
def boot_main_without_skills():
    """Boot fastgeoapi with MCP on and the skills off; yield app.main."""
    with mock.patch.dict(os.environ, {**BOOT, "DEV_FASTGEOAPI_MCP_SKILLS": "false"}, clear=False):
        for key in list(sys.modules):
            if key.startswith("app."):
                del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        yield main_mod


async def _skill_uris_and_instructions(server) -> tuple[set[str], str]:
    from fastmcp import Client

    async with Client(server) as client:
        resources = await client.list_resources()
        instructions = client.instructions or ""
    return {str(r.uri) for r in resources if str(r.uri).startswith("skill://")}, instructions


@pytest.mark.asyncio
async def test_the_mcp_server_serves_skills_by_default(mcp_main):
    from app.mcp.instructions import SKILLS_INSTRUCTIONS

    uris, instructions = await _skill_uris_and_instructions(mcp_main.mcp)

    assert "skill://ogcapi-orientation/SKILL.md" in uris
    assert "skill://ogcapi-features/SKILL.md" in uris
    assert SKILLS_INSTRUCTIONS in instructions


@pytest.mark.asyncio
async def test_the_setting_turns_the_skills_off(main_without_skills):
    from app.mcp.instructions import SERVER_INSTRUCTIONS

    uris, instructions = await _skill_uris_and_instructions(main_without_skills.mcp)

    assert uris == set()
    assert instructions == SERVER_INSTRUCTIONS
