"""End-to-end OAuth tests for the MCP integration using pytest-iam.

These tests boot:
- A real OIDC IdP (canaille) via the pytest-iam ``iam_server`` fixture, in
  a background thread.
- The fastgeoapi app via uvicorn in another thread, configured to use the
  local IdP for MCP authentication.

They exercise the full OAuth ``authorization_code`` dance against the live
``/mcp/*`` endpoints (DCR, ``/authorize`` redirect, callback, token
exchange, authenticated MCP calls), using pytest-iam's ``Server.login()``
and ``Server.consent()`` to skip the IdP UI screens — making the flow
fully programmatic.

This is the automated counterpart of the manual smoke test we run with
``@modelcontextprotocol/inspector`` against the deployed fly.io instance.

Status: scaffolding (fixtures + two health checks). The full OAuth dance
test is added incrementally once the scaffold is validated in CI.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Iterator
from unittest import mock

import httpx
import portpicker
import pytest
import uvicorn


@pytest.fixture
def fastgeoapi_port() -> int:
    """Pre-pick a free port so the OAuth client and the fastgeoapi instance
    can be configured with the same redirect URI before either is started.
    """
    return portpicker.pick_unused_port()


@pytest.fixture
def iam_oauth_client(iam_server, fastgeoapi_port: int):
    """Register an OAuth client in canaille that mirrors the redirect URI
    of the in-process fastgeoapi MCP server.

    The MCP server's upstream callback is ``<APP_URI>/mcp/auth/callback``.
    """
    redirect_uri = f"http://localhost:{fastgeoapi_port}/mcp/auth/callback"
    with iam_server.app.app_context():
        client = iam_server.models.Client(
            client_id="mcp-test-client",
            client_secret="test-secret-do-not-use-in-prod",
            client_name="MCP Test Client",
            redirect_uris=[redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="openid profile email",
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=0,
            token_endpoint_auth_method="client_secret_post",
        )
        iam_server.backend.save(client)
    return client


@pytest.fixture
def fastgeoapi_with_iam(
    iam_server,
    iam_oauth_client,
    fastgeoapi_port: int,
) -> Iterator[str]:
    """Boot fastgeoapi in a uvicorn thread, configured against the local IdP.

    Yields the base URL of the running instance.
    """
    iam_url = iam_server.url.rstrip("/")
    well_known = f"{iam_url}/.well-known/openid-configuration"

    env = {
        "ENV_STATE": "dev",
        "HOST": "localhost",
        "PORT": str(fastgeoapi_port),
        "DEV_APP_URI": f"http://localhost:{fastgeoapi_port}",
        "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        "DEV_FASTGEOAPI_REVERSE_PROXY": "false",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "true",
        "DEV_OPA_ENABLED": "false",
        "DEV_OIDC_WELL_KNOWN_ENDPOINT": well_known,
        "DEV_OIDC_CLIENT_ID": iam_oauth_client.client_id,
        "DEV_OIDC_CLIENT_SECRET": iam_oauth_client.client_secret,
        "DEV_OAUTH2_JWKS_ENDPOINT": f"{iam_url}/oauth/jwks.json",
        "DEV_OAUTH2_TOKEN_ENDPOINT": f"{iam_url}/oauth/token",
        "DEV_OAUTH2_EXPECTED_AUDIENCE": f"http://localhost:{fastgeoapi_port}/geoapi/",
        "DEV_OAUTH2_EXPECTED_ISSUER": iam_url,
        "DEV_PYGEOAPI_BASEURL": f"http://localhost:{fastgeoapi_port}",
        "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
        "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
    }

    with mock.patch.dict(os.environ, env, clear=False):
        # Force a fresh import so module-level `app = ...` is re-evaluated
        # under the patched env.
        for key in list(sys.modules):
            if key.startswith("app."):
                del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()

        from app.main import app

        config = uvicorn.Config(
            app,
            host="localhost",
            port=fastgeoapi_port,
            log_level="warning",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        base_url = f"http://localhost:{fastgeoapi_port}"
        # Wait for the server to be ready
        for _ in range(40):
            try:
                r = httpx.get(f"{base_url}/.well-known/oauth-authorization-server/mcp", timeout=1.0)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        else:
            server.should_exit = True
            thread.join(timeout=5)
            pytest.fail(f"fastgeoapi did not become ready on {base_url}")

        try:
            yield base_url
        finally:
            server.should_exit = True
            thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Scaffolding tests
# ---------------------------------------------------------------------------


def test_well_known_authorization_server_metadata(fastgeoapi_with_iam: str):
    """RFC 8414 metadata is served at the MCP root and points back to itself.

    Confirms fastmcp's OAuth proxy advertises the right issuer and endpoints
    for the locally booted instance.
    """
    base_url = fastgeoapi_with_iam
    r = httpx.get(f"{base_url}/.well-known/oauth-authorization-server/mcp")
    assert r.status_code == 200
    body = r.json()
    expected_issuer = f"{base_url}/mcp/"
    assert body["issuer"] == expected_issuer
    assert body["authorization_endpoint"] == f"{base_url}/mcp/authorize"
    assert body["token_endpoint"] == f"{base_url}/mcp/token"
    assert "authorization_code" in body["grant_types_supported"]


def test_mcp_unauthenticated_request_is_rfc6750_compliant(fastgeoapi_with_iam: str):
    """No-token MCP request returns 401 with the canonical WWW-Authenticate
    header and *without* ``error="invalid_token"`` (RFC 6750 §3.1).

    This guards the local ``RFC6750CompliantAuthMiddleware`` patch — the
    bug exists in the upstream MCP SDK and the patch must keep masking it.
    """
    base_url = fastgeoapi_with_iam
    r = httpx.post(
        f"{base_url}/mcp/",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "e2e-test", "version": "0.1"},
            },
        },
    )
    assert r.status_code == 401
    www_auth = r.headers.get("www-authenticate", "")
    assert 'Bearer realm="mcp"' in www_auth
    assert "resource_metadata=" in www_auth
    # Crucially: no token == no `error="invalid_token"` per RFC 6750 §3.1.
    assert 'error="invalid_token"' not in www_auth
