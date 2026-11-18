"""The skill parameters against the documents and tools of the shipped configurations.

The application is imported inside each test: building a configuration
loads its providers by name, so the builder must come from the same
import of the application as the providers.
"""

import re
from pathlib import Path

import httpx2
import pytest
from fastmcp import FastMCP
from pygeoapi.util import yaml_load

CONFIGURATIONS = ["pygeoapi-config.yml", "pygeoapi-config.demo.yml"]


def _needed_parameters(requirement, operations) -> set[str]:
    """The parameters of the operations a requirement needs, or of every operation."""
    names: set[str] = set()
    for method, path, _, parameters in operations:
        if not requirement.needs or any(
            method == need.method and re.fullmatch(need.path, path) for need in requirement.needs
        ):
            names |= parameters
    return names


@pytest.mark.parametrize("configuration", CONFIGURATIONS)
def test_the_listed_parameters_exist_on_the_operations_of_each_configuration(configuration):
    import duckdb

    from app.mcp.skills.requirements import SKILL_REQUIREMENTS
    from app.mcp.skills.selection import find_operations, select_skills
    from app.pygeoapi.factory import build_openapi

    with Path(configuration).open() as handle:
        config = yaml_load(handle)
    try:
        document = build_openapi(config)
    except duckdb.IOException as error:
        pytest.skip(f"{configuration}: the data it names cannot be read ({error})")
    operations = find_operations(document)
    selected = select_skills(document, SKILL_REQUIREMENTS)

    unknown = {}
    for requirement in SKILL_REQUIREMENTS:
        if requirement.name not in selected:
            continue
        kept = [requirement] + [
            file for path, file in requirement.files.items() if path in selected[requirement.name]
        ]
        for part in kept:
            absent = set(part.parameters) - _needed_parameters(part, operations)
            if absent:
                unknown[requirement.name] = sorted(absent)

    assert unknown == {}


async def _tool_parameters(document: dict) -> dict[str, set[str]]:
    """The argument names of each MCP tool generated from a document."""
    from app.mcp.tools import refresh_tools

    server = FastMCP("skills")
    refresh_tools(server, document, client=httpx2.AsyncClient(base_url="http://test"))
    return {
        tool.name: set(tool.parameters.get("properties", {})) for tool in await server.list_tools()
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", CONFIGURATIONS)
async def test_the_listed_parameters_are_arguments_of_the_tools(configuration):
    import duckdb

    from app.mcp.names import fastmcp_name, tool_names
    from app.mcp.skills.requirements import SKILL_REQUIREMENTS
    from app.mcp.skills.selection import find_operations, select_skills
    from app.pygeoapi.factory import build_openapi

    with Path(configuration).open() as handle:
        config = yaml_load(handle)
    try:
        document = build_openapi(config)
    except duckdb.IOException as error:
        pytest.skip(f"{configuration}: the data it names cannot be read ({error})")
    arguments = await _tool_parameters(document)
    names = tool_names(document)
    operations = find_operations(document)
    selected = select_skills(document, SKILL_REQUIREMENTS)

    unknown = {}
    for requirement in SKILL_REQUIREMENTS:
        if requirement.name not in selected:
            continue
        kept = [requirement] + [
            file for path, file in requirement.files.items() if path in selected[requirement.name]
        ]
        for part in kept:
            tools = {
                names.get(operation_id, fastmcp_name(operation_id))
                for method, path, operation_id, _ in operations
                if not part.needs
                or any(
                    method == need.method and re.fullmatch(need.path, path) for need in part.needs
                )
            }
            accepted = set().union(*(arguments.get(tool, set()) for tool in tools))
            absent = set(part.parameters) - accepted
            if absent:
                unknown[requirement.name] = sorted(absent)

    assert unknown == {}
