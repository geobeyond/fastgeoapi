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
import re
import secrets
from urllib.parse import parse_qs, urlparse

import httpx

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

    RFC 6750 §3.1 says a request with no authentication at all must not
    carry an ``error`` attribute, so clients can start the OAuth flow
    during discovery. fastmcp implements this natively since 4.x (we
    used to patch it); this test pins the behaviour, not the mechanism.
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
    assert www_auth.startswith("Bearer"), www_auth
    assert "resource_metadata=" in www_auth, www_auth
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
            body = response.text
            # fastmcp OAuth error pages bury the actual message under ~2KB
            # of inline CSS; surface <title> + first <p> so CI failures show
            # the real reason (e.g. "Token exchange with identity provider
            # failed: ...") instead of HTML boilerplate.
            title = re.search(r"<title>([^<]+)</title>", body)
            message = re.search(r"<p>([^<]+)</p>", body)
            detail = " — ".join(m.group(1).strip() for m in (title, message) if m)
            raise AssertionError(
                f"Expected redirect, got {response.status_code}: {detail or body[:300]}"
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
