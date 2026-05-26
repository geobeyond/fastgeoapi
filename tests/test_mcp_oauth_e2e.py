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
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import sys
import threading
import time
from collections.abc import Iterator
from unittest import mock
from urllib.parse import parse_qs, urlparse

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
    The ``iam_server`` fixture is session-scoped, so previously-registered
    clients from earlier tests persist in its in-memory backend — we
    delete any leftover before saving to keep client_id unique and the
    redirect_uri current for this run's port.
    """
    redirect_uri = f"http://localhost:{fastgeoapi_port}/mcp/auth/callback"
    with iam_server.app.app_context():
        existing = iam_server.backend.query(iam_server.models.Client, client_id="mcp-test-client")
        for stale in existing:
            iam_server.backend.delete(stale)
        # canaille stores ``scope`` as ``list[str]``; passing a string here
        # would break the set-based consent check in is_consent_needed().
        client = iam_server.models.Client(
            client_id="mcp-test-client",
            client_secret="test-secret-do-not-use-in-prod",
            client_name="MCP Test Client",
            redirect_uris=[redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=["openid", "profile", "email"],
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=0,
            # fastmcp's OIDCProxy sends upstream client creds via HTTP Basic.
            token_endpoint_auth_method="client_secret_basic",
        )
        iam_server.backend.save(client)
    try:
        yield client
    finally:
        with iam_server.app.app_context():
            for stale in iam_server.backend.query(
                iam_server.models.Client, client_id="mcp-test-client"
            ):
                iam_server.backend.delete(stale)


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


# ---------------------------------------------------------------------------
# Full OAuth authorization_code flow
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Return a (code_verifier, code_challenge) pair for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _follow_until(
    client: httpx.Client,
    response: httpx.Response,
    stop_prefix: str,
    max_hops: int = 12,
) -> httpx.Response:
    """Step through 3xx redirects until the next Location starts with
    ``stop_prefix``, then return that response (the one whose Location header
    points at ``stop_prefix``). Uses the shared client so cookies persist.
    """
    for _ in range(max_hops):
        if response.status_code not in (301, 302, 303, 307, 308):
            raise AssertionError(
                f"Expected redirect, got {response.status_code}: {response.text[:300]}"
            )
        location = response.headers.get("location", "")
        if not location:
            raise AssertionError("Redirect missing Location header")
        next_url = str(httpx.URL(str(response.url)).join(location))
        if next_url.startswith(stop_prefix):
            return response
        response = client.get(next_url, follow_redirects=False)
    raise AssertionError(f"Too many redirects before reaching {stop_prefix}")


def test_full_oauth_authorization_code_flow(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
):
    """End-to-end ``authorization_code`` + PKCE flow through the MCP proxy.

    Walks every hop of the dance manually so each step is asserted:
    DCR -> /authorize -> /consent (fastmcp interstitial) -> canaille
    /oauth/authorize (pre-logged-in + pre-consented) -> /mcp/auth/callback
    -> client redirect with code -> /token -> authenticated /mcp/ initialize.
    """
    base_url = fastgeoapi_with_iam

    # Pre-authorize a user against the upstream IdP so the canaille login
    # and consent screens are skipped programmatically.
    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    client_redirect = "http://localhost:1/cb"  # placeholder, never fetched
    state = secrets.token_urlsafe(16)
    code_verifier, code_challenge = _pkce_pair()

    with httpx.Client(timeout=10.0) as client:
        # 1. Dynamic Client Registration (RFC 7591).
        r = client.post(
            f"{base_url}/mcp/register",
            json={
                "redirect_uris": [client_redirect],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "openid profile email",
                "token_endpoint_auth_method": "none",
                "client_name": "fastgeoapi e2e client",
            },
        )
        assert r.status_code in (200, 201), r.text
        dcr = r.json()
        mcp_client_id = dcr["client_id"]
        # fastmcp's ProxyDCRClient is a public client (auth method "none"),
        # so no client_secret is required at the token endpoint.

        # 2. /mcp/authorize -> 302 to local /mcp/consent interstitial.
        r = client.get(
            f"{base_url}/mcp/authorize",
            params={
                "response_type": "code",
                "client_id": mcp_client_id,
                "redirect_uri": client_redirect,
                "scope": "openid profile email",
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert r.status_code in (302, 303, 307), r.text
        consent_location = r.headers["location"]
        assert "/consent?txn_id=" in consent_location, consent_location

        # 3. GET /mcp/consent -> HTML form with csrf_token + MCP_CONSENT_STATE
        # cookie that the POST handler will double-submit-check against.
        r = client.get(
            str(httpx.URL(str(r.url)).join(consent_location)),
            follow_redirects=False,
        )
        assert r.status_code == 200, r.text[:300]
        csrf_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
        txn_match = re.search(r'name="txn_id"\s+value="([^"]+)"', r.text)
        assert csrf_match and txn_match, "consent form missing csrf_token/txn_id"
        csrf_token = csrf_match.group(1)
        txn_id = txn_match.group(1)

        # 4. POST /mcp/consent approve -> 302 to canaille /oauth/authorize.
        r = client.post(
            f"{base_url}/mcp/consent",
            data={
                "txn_id": txn_id,
                "action": "approve",
                "csrf_token": csrf_token,
            },
            follow_redirects=False,
        )
        assert r.status_code in (302, 303), r.text[:300]
        canaille_url = r.headers["location"]
        assert canaille_url.startswith(iam_server.url.rstrip("/")), canaille_url

        # 5. GET canaille /oauth/authorize -> with login+consent pre-applied,
        # canaille issues 302 back to /mcp/auth/callback?code=...
        r = client.get(canaille_url, follow_redirects=False)
        callback = _follow_until(client, r, f"{base_url}/mcp/auth/callback")
        callback_location = str(httpx.URL(str(callback.url)).join(callback.headers["location"]))
        assert callback_location.startswith(f"{base_url}/mcp/auth/callback"), callback_location

        # 6. /mcp/auth/callback -> 302 to client_redirect with code+state.
        r = client.get(callback_location, follow_redirects=False)
        final = _follow_until(client, r, client_redirect)
        final_location = str(httpx.URL(str(final.url)).join(final.headers["location"]))
        final_params = parse_qs(urlparse(final_location).query)
        assert final_params.get("state") == [state]
        assert "code" in final_params, final_location
        mcp_auth_code = final_params["code"][0]

        # 7. Token exchange. Public client (PKCE) -> no client_secret.
        r = client.post(
            f"{base_url}/mcp/token",
            data={
                "grant_type": "authorization_code",
                "code": mcp_auth_code,
                "redirect_uri": client_redirect,
                "client_id": mcp_client_id,
                "code_verifier": code_verifier,
            },
        )
        assert r.status_code == 200, r.text
        token_body = r.json()
        access_token = token_body["access_token"]
        assert token_body.get("token_type", "").lower() == "bearer"

        # 8. Authenticated MCP call. Auth must succeed; the upstream MCP
        # response is irrelevant here — we only assert that the request was
        # not rejected at the auth layer.
        r = client.post(
            f"{base_url}/mcp/",
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
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {access_token}",
            },
        )
        assert r.status_code != 401, r.text[:300]
        assert r.status_code < 500, r.text[:300]
