"""Tool annotations: what each generated tool may do.

MCP clients read ``readOnlyHint`` and ``destructiveHint`` to decide how
much to ask the user before a call. The spec gives
``destructiveHint`` a default of true and counts it, like
``idempotentHint``, only when ``readOnlyHint`` is false. Without
annotations a client cannot tell ``deleteJob`` from a read.
"""

import pytest
from fastmcp import Client

from app.mcp.annotations import annotations_for


def test_a_read_is_read_only_and_closed():
    hints = annotations_for("GET", "/collections/lakes/items", "getLakesFeatures")

    assert hints.read_only_hint is True
    assert hints.open_world_hint is False


def test_options_is_a_read():
    assert annotations_for(
        "OPTIONS", "/collections/lakes/items", "optionsLakesFeatures"
    ).read_only_hint


def test_a_cql2_query_is_a_read():
    hints = annotations_for("POST", "/collections/lakes/items", "getCQL2LakesFeatures")

    assert hints.read_only_hint is True


def test_the_cql2_post_of_an_editable_collection_adds_without_destroying():
    hints = annotations_for("POST", "/collections/lakes/items", "getCQL2OrAddLakesFeatures")

    assert hints.read_only_hint is False
    assert hints.destructive_hint is False


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("PUT", "/collections/lakes/items/{featureId}"),
        ("DELETE", "/collections/lakes/items/{featureId}"),
        ("DELETE", "/jobs/{jobId}"),
    ],
)
def test_replacing_or_deleting_is_destructive_and_idempotent(method, path):
    hints = annotations_for(method, path, "anything")

    assert hints.read_only_hint is False
    assert hints.destructive_hint is True
    assert hints.idempotent_hint is True


def test_running_a_process_is_not_read_only_and_claims_nothing_else():
    """A process may write data or call other services, so only readOnlyHint is set."""
    hints = annotations_for("POST", "/processes/hello-world/execution", "executeHello-worldJob")

    assert hints.read_only_hint is False
    assert hints.destructive_hint is None
    assert hints.open_world_hint is None


async def _tools(mcp_main) -> dict:
    async with Client(mcp_main.mcp) as client:
        return {tool.name: tool for tool in await client.list_tools()}


@pytest.mark.asyncio
async def test_the_generated_tools_carry_the_annotations(mcp_main):
    tools = await _tools(mcp_main)

    assert tools["getLakesFeatures"].annotations.read_only_hint is True
    assert tools["executeHello_worldJob"].annotations.read_only_hint is False


@pytest.mark.asyncio
async def test_the_title_is_the_operation_summary(mcp_main):
    tools = await _tools(mcp_main)

    assert tools["getLandingPage"].title == "Landing page"
    assert tools["getLakesFeatures"].title == "Get Large Lakes items"
