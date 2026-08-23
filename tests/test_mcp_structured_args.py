"""Regression sentinels for structured-argument forwarding over MCP.

Observed on fastmcp 2.14.x: nested/structured tool arguments were stringified on the MCP → pygeoapi hop. Two symptoms of the same marshalling defect:

- Bug 5: the OGC Processes execute body arrived as a string, so
  pygeoapi failed with ``'str' object has no attribute 'get'`` —
  HTTP 400 for ANY input, killing the whole Processes/Jobs surface
  through the wrapper.
- Bug 4: array-valued query parameters (``bbox``, ``properties``)
  were serialized as ``str(list)``, silently corrupting filters.

Both were fixed by the fastmcp 3.x ``from_openapi`` rewrite. These tests pin the behavior so a regression in the tool layer cannot come back silently.
"""

from __future__ import annotations

import json
import os
import sys
from unittest import mock

import httpx
import pytest


@pytest.fixture
def mcp_main():
    """Boot fastgeoapi with MCP enabled and no auth; yield app.main."""
    env = {
        "ENV_STATE": "dev",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        for key in list(sys.modules):
            if key.startswith("app."):
                del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        yield main_mod


def _result(res):
    """Unwrap the tool payload from a fastmcp tool result.

    Tools whose response schema is a declared object get structured
    content (wrapped under ``result``); others carry the raw JSON body
    as text content only.
    """
    structured = res.structured_content
    if structured:
        return structured.get("result", structured)
    return json.loads(res.content[0].text)


@pytest.mark.asyncio
async def test_execute_process_body_forwarded_as_json_object(mcp_main):
    """The execute body must reach pygeoapi as a parsed JSON object.

    On fastmcp 2.14+ this exact call — the process's own documented
    example — returned HTTP 400 ``'str' object has no attribute
    'get'`` because the ``inputs`` mapping was stringified in transit.
    """
    from fastmcp import Client

    async with Client(mcp_main.mcp) as client:
        res = await client.call_tool("executeHello_worldJob", {"inputs": {"name": "World"}})

    payload = _result(res)
    assert payload.get("id") == "echo", payload
    assert payload.get("value") == "Hello World!", payload


@pytest.mark.asyncio
async def test_execute_process_with_flat_args_rejected_cleanly(mcp_main):
    """Flattened arguments must get a clean 400, not an internal leak.

    A client that skips the ``inputs`` wrapper must receive pygeoapi's proper
    ``MissingParameterValue`` rejection — not the ``AttributeError``
    surfaced as an opaque error message.
    """
    from fastmcp import Client

    async with Client(mcp_main.mcp) as client:
        with pytest.raises(Exception) as exc_info:
            await client.call_tool("executeHello_worldJob", {"name": "World"})

    message = str(exc_info.value)
    assert "MissingParameterValue" in message or "missing request data" in message, message
    assert "has no attribute" not in message, message


@pytest.mark.asyncio
async def test_array_query_params_forwarded_intact(mcp_main):
    """Array query params (bbox, properties) must survive the MCP hop.

    The MCP tool result is compared against the same query issued
    directly to the raw pygeoapi sub-app: identical ``numberMatched``
    proves the filter was applied, not dropped or stringified (a
    ``str(list)`` bbox matches nothing or errors out).
    """
    from fastmcp import Client

    bbox = [-90, -45, 90, 45]

    # Direct HTTP baseline on the raw sub-app (no MCP in the path):
    # the holder is the same target the MCP transport uses.
    transport = httpx.ASGITransport(app=mcp_main._pygeoapi_holder)
    async with httpx.AsyncClient(transport=transport, base_url="http://baseline") as http:
        unfiltered = (await http.get("/collections/lakes/items?f=json&limit=2")).json()
        filtered = (
            await http.get(
                f"/collections/lakes/items?f=json&limit=2&bbox={','.join(map(str, bbox))}"
            )
        ).json()

    assert unfiltered["numberMatched"] > filtered["numberMatched"], (
        "demo data must make the bbox filter selective for this test to be meaningful"
    )

    async with Client(mcp_main.mcp) as client:
        res_plain = await client.call_tool("getLakesFeatures", {"limit": 2})
        res_bbox = await client.call_tool("getLakesFeatures", {"limit": 2, "bbox": bbox})
        res_props = await client.call_tool("getLakesFeatures", {"limit": 2, "properties": ["name"]})

    assert _result(res_plain).get("numberMatched") == unfiltered["numberMatched"]
    assert _result(res_bbox).get("numberMatched") == filtered["numberMatched"]
    # properties selects fields, it must not change the match count
    assert _result(res_props).get("numberMatched") == unfiltered["numberMatched"]
