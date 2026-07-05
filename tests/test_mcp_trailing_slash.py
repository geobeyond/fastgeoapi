"""Trailing-slash robustness for the MCP mount and discovery routes.

Claude Desktop's custom-connector UI normalizes the server URL by
stripping the trailing slash, so real clients POST ``/mcp`` (no slash).
Starlette's ``redirect_slashes`` would answer 307 — and behind a
reverse proxy that hasn't rewritten the scheme (fly.io), the
``Location`` header downgrades to ``http://``, which breaks POSTs
(cross-scheme redirect + method rewrite on the follow-up 301).

These tests pin the no-redirect behavior: the no-slash variants must
be served directly, identical to their slash counterparts.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest
from starlette.testclient import TestClient

MCP_ACCEPT_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}

INITIALIZE_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "trailing-slash-test", "version": "0.0.1"},
    },
}


def _reload_app_main():
    """Force a clean reload so module-level ``app = ...`` re-evaluates."""
    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    import app.main as main_mod

    return main_mod


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
        yield _reload_app_main().app


@pytest.fixture
def mcp_app_with_oauth():
    """Boot fastgeoapi with MCP + OIDC (discovery mocked); yield the app."""
    env = {
        "ENV_STATE": "dev",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "true",
        "DEV_OPA_ENABLED": "false",
        "DEV_OIDC_WELL_KNOWN_ENDPOINT": "https://example.logto.app/oidc/.well-known/openid-configuration",
        "DEV_OIDC_CLIENT_ID": "test-client-id",
        "DEV_OIDC_CLIENT_SECRET": "test-client-secret",
        "DEV_APP_URI": "http://localhost:5000",
    }
    mock_oidc_config = {
        "issuer": "https://example.logto.app/oidc",
        "authorization_endpoint": "https://example.logto.app/oidc/auth",
        "token_endpoint": "https://example.logto.app/oidc/token",
        "jwks_uri": "https://example.logto.app/oidc/jwks",
        "introspection_endpoint": "https://example.logto.app/oidc/token/introspection",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }
    mock_response = mock.MagicMock()
    mock_response.json.return_value = mock_oidc_config
    mock_response.raise_for_status = mock.MagicMock()

    with mock.patch.dict(os.environ, env, clear=False):
        with (
            mock.patch("requests.get", return_value=mock_response),
            mock.patch("httpx.get", return_value=mock_response),
        ):
            yield _reload_app_main().app


def test_post_mcp_without_trailing_slash_is_not_redirected(mcp_app_no_auth):
    """``POST /mcp`` must be served directly, not 30x-redirected.

    Clients that strip the trailing slash (Claude Desktop connector UI)
    would otherwise chase a scheme-downgraded ``Location`` behind the
    reverse proxy and lose the POST body/method along the way.
    """
    client = TestClient(mcp_app_no_auth, raise_server_exceptions=False)

    r_no_slash = client.post(
        "/mcp",
        json=INITIALIZE_PAYLOAD,
        headers=MCP_ACCEPT_HEADERS,
        follow_redirects=False,
    )
    assert r_no_slash.status_code not in (301, 302, 307, 308), (
        f"POST /mcp must not redirect (got {r_no_slash.status_code} "
        f"-> {r_no_slash.headers.get('location')})"
    )

    # And it must behave exactly like the canonical slash variant.
    r_slash = client.post(
        "/mcp/",
        json=INITIALIZE_PAYLOAD,
        headers=MCP_ACCEPT_HEADERS,
        follow_redirects=False,
    )
    assert r_no_slash.status_code == r_slash.status_code


def test_get_mcp_without_trailing_slash_is_not_redirected(mcp_app_no_auth):
    """The GET (server->client stream) variant must not redirect either."""
    client = TestClient(mcp_app_no_auth, raise_server_exceptions=False)
    r = client.get(
        "/mcp",
        headers={"Accept": "text/event-stream"},
        follow_redirects=False,
    )
    assert r.status_code not in (301, 302, 307, 308)


def test_prm_without_trailing_slash_served_directly(mcp_app_with_oauth):
    """RFC 9728 PRM must answer on both slash variants without redirects.

    A client that normalized the resource to ``.../mcp`` builds the PRM
    URL without the trailing slash; chasing a scheme-downgraded 307 is
    not an acceptable answer.
    """
    client = TestClient(mcp_app_with_oauth, raise_server_exceptions=False)

    r_no_slash = client.get(
        "/.well-known/oauth-protected-resource/mcp",
        follow_redirects=False,
    )
    assert r_no_slash.status_code == 200, (
        f"expected 200, got {r_no_slash.status_code} -> {r_no_slash.headers.get('location')}"
    )

    r_slash = client.get(
        "/.well-known/oauth-protected-resource/mcp/",
        follow_redirects=False,
    )
    assert r_slash.status_code == 200
    assert r_no_slash.json() == r_slash.json()
