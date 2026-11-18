"""The skill texts against their requirements and the generated OpenAPI documents."""

import re
from pathlib import Path

import httpx2
import pytest
from fastmcp import FastMCP
from fastmcp.skills import Skill
from pygeoapi.util import yaml_load
from pygeofilter.parsers.cql2_text import parse as parse_cql2_text

from app.mcp.names import fastmcp_name, tool_names
from app.mcp.skills.requirements import SKILL_REQUIREMENTS, SKILLS_DIRECTORY
from app.mcp.skills.selection import FileRequirement, find_operations, select_skills
from app.mcp.tools import refresh_tools
from app.pygeoapi.factory import build_openapi

TOOL_NAME = re.compile(r"\b(get|execute|describe)[A-Z]\w*")
CONFIGURATIONS = ["pygeoapi-config.yml", "pygeoapi-config.demo.yml"]
OGC_QUERY_PARAMETERS = frozenset(
    {
        "f",
        "lang",
        "bbox",
        "bbox-crs",
        "crs",
        "datetime",
        "limit",
        "offset",
        "properties",
        "sortby",
        "skipGeometry",
        "filter",
        "filter-lang",
        "filter-crs",
        "q",
        "width",
        "height",
        "transparent",
        "bgcolor",
        "subset",
        "subset-crs",
        "center",
        "center-crs",
        "scale-denominator",
        "Prefer",
    }
)
"""Query parameters of OGC API Features, Processes and Maps a text may name."""
BACKTICKED = re.compile(r"`([^`]+)`")


def _texts():
    for requirement in SKILL_REQUIREMENTS:
        folder = SKILLS_DIRECTORY / requirement.name
        yield folder / "SKILL.md", requirement
        for path, file in requirement.files.items():
            yield folder / path, file


@pytest.mark.parametrize("requirement", SKILL_REQUIREMENTS, ids=lambda r: r.name)
def test_every_folder_is_a_valid_skill(requirement):
    skill = Skill.from_directory(SKILLS_DIRECTORY / requirement.name)

    assert skill.name == requirement.name
    assert 0 < len(skill.description) < 1024


def test_every_folder_has_a_requirement_and_back():
    folders = {path.parent.name for path in SKILLS_DIRECTORY.glob("*/SKILL.md")}

    assert folders == {requirement.name for requirement in SKILL_REQUIREMENTS}
    for requirement in SKILL_REQUIREMENTS:
        for path in requirement.files:
            assert (SKILLS_DIRECTORY / requirement.name / path).is_file(), path


@pytest.mark.parametrize("text, requirement", list(_texts()), ids=lambda v: getattr(v, "name", ""))
def test_every_listed_parameter_is_named_in_the_text(text: Path, requirement: FileRequirement):
    content = text.read_text()

    missing = [name for name in requirement.parameters if f"`{name}`" not in content]

    assert missing == [], f"{text}: {missing}"


@pytest.mark.parametrize("text", [text for text, _ in _texts()], ids=lambda t: t.parent.name)
def test_no_text_names_a_tool(text: Path):
    assert TOOL_NAME.findall(text.read_text()) == []


@pytest.mark.parametrize("requirement", SKILL_REQUIREMENTS, ids=lambda r: r.name)
def test_every_query_parameter_a_text_names_is_listed(requirement):
    folder = SKILLS_DIRECTORY / requirement.name
    listed = set(requirement.parameters).union(
        *(file.parameters for file in requirement.files.values())
    )
    texts = [folder / "SKILL.md", *(folder / path for path in requirement.files)]

    named = {
        token
        for text in texts
        for token in BACKTICKED.findall(text.read_text())
        if token in OGC_QUERY_PARAMETERS
    }

    assert named - listed == set()


def test_the_complete_cql2_text_expressions_parse():
    table = [
        line.split("|")[2]
        for line in (SKILLS_DIRECTORY / "ogcapi-features" / "cql2.md").read_text().splitlines()
        if line.startswith("|") and line.count("|") >= 4
    ]
    expressions = [
        span
        for cell in table
        for span in BACKTICKED.findall(cell)
        if " " in span and "..." not in span
    ]

    failing = []
    for expression in expressions:
        try:
            parse_cql2_text(expression)
        except Exception:
            failing.append(expression)

    assert expressions
    assert failing == []


def _needed_parameters(requirement: FileRequirement, operations) -> set[str]:
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
    server = FastMCP("skills")
    refresh_tools(server, document, client=httpx2.AsyncClient(base_url="http://test"))
    return {
        tool.name: set(tool.parameters.get("properties", {})) for tool in await server.list_tools()
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("configuration", CONFIGURATIONS)
async def test_the_listed_parameters_are_arguments_of_the_tools(configuration):
    import duckdb

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
