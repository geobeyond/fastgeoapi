"""The skills a provider serves for an OpenAPI document."""

import pytest
from fastmcp import Client, FastMCP

from app.mcp.instructions import SERVER_INSTRUCTIONS, build_server_instructions
from app.mcp.skills.provider import OgcApiSkillProvider
from app.mcp.skills.requirements import SKILLS_DIRECTORY


def _spec(*paths: str) -> dict:
    """An OpenAPI document with a GET on each path."""
    ok = {"200": {"description": "ok"}}
    return {
        "openapi": "3.0.2",
        "info": {"title": "test", "version": "1"},
        "paths": {
            path: {"get": {"operationId": f"op{n}", "responses": ok}}
            for n, path in enumerate(paths)
        },
    }


async def _skill_uris(server: FastMCP) -> set[str]:
    async with Client(server) as client:
        return {
            str(r.uri) for r in await client.list_resources() if str(r.uri).startswith("skill://")
        }


def _server(provider: OgcApiSkillProvider) -> FastMCP:
    server = FastMCP("test")
    server.add_provider(provider)
    return server


@pytest.mark.asyncio
async def test_only_the_selected_skills_are_resources():
    uris = await _skill_uris(_server(OgcApiSkillProvider(_spec("/collections/lakes/items"))))

    assert "skill://ogcapi-features/SKILL.md" in uris
    assert "skill://ogcapi-features/cql2.md" not in uris
    assert all(
        uri.startswith(("skill://ogcapi-orientation/", "skill://ogcapi-features/")) for uri in uris
    )


@pytest.mark.asyncio
async def test_selecting_again_changes_the_resources():
    provider = OgcApiSkillProvider(_spec("/collections/lakes/items"))
    server = _server(provider)

    provider.select(_spec("/collections/lakes/items", "/collections/rome/map"))

    assert "skill://ogcapi-maps/SKILL.md" in await _skill_uris(server)


@pytest.mark.asyncio
async def test_a_skill_file_reads_as_its_text():
    server = _server(OgcApiSkillProvider(_spec("/collections/lakes/items")))

    async with Client(server) as client:
        (content,) = await client.read_resource("skill://ogcapi-features/SKILL.md")

    assert content.text == (SKILLS_DIRECTORY / "ogcapi-features" / "SKILL.md").read_text()


@pytest.mark.asyncio
async def test_a_server_with_only_orientation_starts_and_lists_it():
    uris = await _skill_uris(_server(OgcApiSkillProvider(_spec())))

    assert "skill://ogcapi-orientation/SKILL.md" in uris
    assert all(uri.startswith("skill://ogcapi-orientation/") for uri in uris)


def test_the_instructions_mention_skills_only_when_they_are_on():
    assert build_server_instructions(skills=False) == SERVER_INSTRUCTIONS
    assert build_server_instructions(skills=True).startswith(SERVER_INSTRUCTIONS)
    assert "skill" in build_server_instructions(skills=True).removeprefix(SERVER_INSTRUCTIONS)
