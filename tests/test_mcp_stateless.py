"""Stateless Streamable HTTP sentinels for the MCP mount.

The fly.io deployment auto-suspends the machine on idle and rebuilds it
on every deploy: with the default *stateful* streamable HTTP transport,
the server-side session dies while MCP clients (Claude Desktop) keep a
stale ``mcp-session-id`` and dead connections — the UI still shows
"connected" but tool calls fail ("couldn't send tool approval").

With ``stateless_http=True`` every request is self-contained (a fresh
transport per request), so suspend/resume and deploys are transparent.
The trade-off — no server-initiated notifications — is irrelevant for
this tools-only, OpenAPI-generated server.

These tests pin the stateless behavior: a well-formed MCP request with
NO prior ``initialize`` and NO ``mcp-session-id`` header must succeed.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest
from starlette.testclient import TestClient

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

TOOLS_LIST_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {},
}


@pytest.fixture
def mcp_app_no_auth():
    """Boot fastgeoapi with MCP enabled and no auth; yield the ASGI app."""
    env = {
        "ENV_STATE": "dev",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
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

        yield main_mod.app


def test_mcp_request_without_session_id_succeeds(mcp_app_no_auth):
    """A sessionless ``tools/list`` must be served, not rejected.

    In stateful mode the transport answers 400 ("Missing session ID")
    unless the client completed ``initialize`` on the same session —
    exactly what breaks after a fly suspend or deploy. Stateless mode
    accepts each request on its own.
    """
    # Context manager: runs the app lifespan, which boots the MCP
    # session manager (otherwise any MCP request 500s regardless of
    # session handling).
    with TestClient(mcp_app_no_auth, raise_server_exceptions=False) as client:
        r = client.post("/mcp/", json=TOOLS_LIST_PAYLOAD, headers=MCP_HEADERS)

    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:300]}"
    body = r.text
    # SSE or plain JSON depending on transport config; both carry the
    # JSON-RPC result with the tool inventory.
    assert '"result"' in body and '"tools"' in body, body[:300]
    assert '"error"' not in body.split('"result"')[0], body[:300]
