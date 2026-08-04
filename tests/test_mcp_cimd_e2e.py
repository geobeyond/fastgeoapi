"""End-to-end CIMD tests: URL-identified clients against our OAuth AS.

CIMD (Client ID Metadata Document,
[draft-ietf-oauth-client-id-metadata-document](https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/))
lets an MCP client identify itself with an HTTPS URL that serves its own
OAuth metadata, instead of registering ahead of time. It is one of the
three standards tested by the OpenID AIIM interoperability program, and
these tests answer — in our own suite, before pairing with a partner —
which rows of that program's CIMD matrix our authorization server can
actually satisfy:

- *Client ID Metadata* — the document is fetched, validated and turned
  into a usable client
- *redirect_uris support* — redirects are validated against the document
- *Authorization code grant with PKCE / none* — public URL-identified
  client completes the flow
- *Authorization code grant with PKCE / JWT* — ``private_key_jwt`` client
  authentication using keys from the document (inline ``jwks``)
- *Client secret* — rejected by design: a URL-identified client cannot
  hold a usable shared secret

**Why the fetcher is patched.** ``CIMDFetcher`` deliberately refuses
loopback and private addresses (it fetches a URL supplied by the
client — an SSRF sink by definition), so a document served from the test
process is unreachable by design. These tests replace the SSRF-safe
fetch with an in-process one, which keeps every layer above it real: URL
detection, document validation, client_id matching, client synthesis,
redirect validation, PKCE, and the token endpoint's client
authentication. Only the socket is faked.
"""

from __future__ import annotations

import contextlib
import json
import secrets
import time

import httpx
import pytest
from authlib.jose import JsonWebKey, jwt

from tests.mcp_e2e_client import CLIENT_REDIRECT_URI, MCPOAuthClient, pkce_pair

# CIMD requires https, a host and a non-root path. The host is never
# resolved (the fetch is patched). Each document gets a unique URL:
# fastmcp's OAuth proxy persists registered clients on disk (the reason
# the fly deployment mounts a volume for it), and a stored client
# short-circuits document re-validation — reusing one URL across tests
# would leak a previous test's client into the next.
def cimd_client_id() -> str:
    """Return a unique CIMD document URL."""
    return f"https://clients.example.test/fastgeoapi/{secrets.token_hex(6)}.json"

CIMD_SCOPE = "openid profile email"

ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


def cimd_document(**overrides) -> dict:
    """Build a minimal valid CIMD document, overridable per test."""
    document = {
        "client_id": cimd_client_id(),
        "client_name": "fastgeoapi CIMD e2e client",
        "redirect_uris": [CLIENT_REDIRECT_URI],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": CIMD_SCOPE,
    }
    document.update(overrides)
    return document


@pytest.fixture
def serve_cimd_documents(monkeypatch):
    """Serve CIMD documents in-process, bypassing the SSRF guard.

    Returns a callable that publishes a document at its own ``client_id``
    URL. Unpublished URLs raise the same error the real fetcher would.
    """
    from fastmcp.server.auth import cimd as cimd_module
    from fastmcp.server.auth.ssrf import SSRFFetchError, SSRFFetchResponse

    published: dict[str, dict] = {}

    async def fake_fetch(url: str, **_kwargs) -> SSRFFetchResponse:
        if url not in published:
            raise SSRFFetchError(f"no CIMD document published at {url}")
        return SSRFFetchResponse(
            content=json.dumps(published[url]).encode(),
            status_code=200,
            # No caching: each test gets its own document for the same URL.
            headers={"Cache-Control": "no-store"},
        )

    monkeypatch.setattr(cimd_module, "ssrf_safe_fetch_response", fake_fetch)

    def publish(document: dict, at: str | None = None) -> str:
        """Publish a document, optionally at a URL other than its client_id."""
        url = at or str(document["client_id"])
        published[url] = document
        return url

    return publish


@pytest.fixture
def logged_in_user(iam_server, iam_oauth_client):
    """Pre-authenticate a user upstream so IdP screens are skipped."""
    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)
    return user


def test_cimd_is_advertised_in_authorization_server_metadata(fastgeoapi_with_iam: str):
    """The AS metadata must announce CIMD and its client auth methods.

    This is what a CIMD-capable client reads before deciding it can
    identify itself by URL.
    """
    response = httpx.get(f"{fastgeoapi_with_iam}/.well-known/oauth-authorization-server/mcp")
    assert response.status_code == 200, response.text[:200]
    metadata = response.json()

    assert metadata.get("client_id_metadata_document_supported") is True, metadata
    auth_methods = metadata.get("token_endpoint_auth_methods_supported") or []
    assert "private_key_jwt" in auth_methods, auth_methods
    assert "none" in auth_methods, auth_methods


@pytest.mark.asyncio
async def test_cimd_url_client_completes_flow_and_calls_tools(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    logged_in_user,
):
    """A URL-identified client authorizes and uses the MCP server.

    Matrix rows covered: *Client ID Metadata*, *redirect_uris support*,
    and *Authorization code grant with PKCE* with ``none`` client
    authentication — no prior registration anywhere.
    """
    from tests.mcp_e2e_client import authenticated_mcp_client

    client_id = serve_cimd_documents(cimd_document())

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam, client_id=client_id, scope=CIMD_SCOPE)
    token = oauth.run_dance()
    assert token

    async with authenticated_mcp_client(fastgeoapi_with_iam, oauth=oauth) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools}, "no tools advertised to the CIMD client"


def test_cimd_redirect_uri_outside_the_document_is_rejected(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    logged_in_user,
):
    """Redirects are validated against the document, not merely echoed.

    The *redirect_uris support* row means enforcement: a redirect the
    document does not list must not be honoured, or a rogue client could
    redirect an authorization code anywhere.
    """
    client_id = serve_cimd_documents(cimd_document())

    _verifier, challenge = pkce_pair()
    with httpx.Client(timeout=10.0) as http:
        response = http.get(
            f"{fastgeoapi_with_iam}/mcp/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://localhost:9/attacker",
                "scope": CIMD_SCOPE,
                "state": secrets.token_urlsafe(16),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )

    # Either a direct error response, or a redirect carrying an OAuth
    # error — never a redirect to the unregistered target.
    location = response.headers.get("location", "")
    assert not location.startswith("http://localhost:9/attacker"), location
    if response.status_code in (302, 303, 307):
        assert "error=" in location, location
    else:
        assert response.status_code >= 400, response.status_code


def test_cimd_document_with_shared_secret_auth_never_yields_a_token(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    logged_in_user,
):
    """Shared-secret client authentication is invalid in a CIMD document.

    A client identified only by a public URL cannot keep a secret, so the
    document is refused and no token can ever be issued — in the interop
    matrix the *Client secret* rows stay blank for us by design, not by
    omission. The rejection may land at any hop (the consent
    interstitial is rendered before the client is resolved), so the
    invariant asserted here is the outcome: no access token.
    """
    client_id = serve_cimd_documents(
        cimd_document(token_endpoint_auth_method="client_secret_basic")
    )

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam, client_id=client_id, scope=CIMD_SCOPE)
    with contextlib.suppress(AssertionError):
        oauth.run_dance()

    assert oauth.access_token is None, "a shared-secret CIMD document must not yield a token"


def test_cimd_client_id_must_match_the_document_url(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    logged_in_user,
):
    """A document claiming a client_id other than its own URL is invalid.

    Without this check anyone could host a document impersonating
    another client's identifier.
    """
    impostor_url = cimd_client_id()
    # The document keeps the canonical client_id but is served elsewhere.
    serve_cimd_documents(cimd_document(), at=impostor_url)

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam, client_id=impostor_url, scope=CIMD_SCOPE)
    with contextlib.suppress(AssertionError):
        oauth.run_dance()

    assert oauth.access_token is None, "a mismatched CIMD document must not yield a token"


def test_cimd_private_key_jwt_authenticates_the_token_request(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    logged_in_user,
):
    """``private_key_jwt`` with keys from the document authenticates /token.

    Matrix row: *Authorization code grant with PKCE / JWT*. The client
    proves possession of the key published in its own metadata document
    (inline ``jwks``) instead of presenting a secret.
    """
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    public_jwk = key.as_dict(is_private=False, alg="RS256", use="sig", kid="cimd-e2e")
    client_id = serve_cimd_documents(
        cimd_document(
            token_endpoint_auth_method="private_key_jwt",
            jwks={"keys": [public_jwk]},
        )
    )

    # The audience is the token endpoint the authorization server
    # advertises: a conforming client has no other value to sign.
    metadata = httpx.get(
        f"{fastgeoapi_with_iam}/.well-known/oauth-authorization-server/mcp"
    ).json()
    token_endpoint = metadata["token_endpoint"]
    now = int(time.time())
    assertion = jwt.encode(
        {"alg": "RS256", "kid": "cimd-e2e", "typ": "JWT"},
        {
            "iss": client_id,
            "sub": client_id,
            "aud": token_endpoint,
            "jti": secrets.token_urlsafe(16),
            "iat": now,
            "exp": now + 120,
        },
        key,
    ).decode()

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam, client_id=client_id, scope=CIMD_SCOPE)
    verifier, challenge = pkce_pair()

    with httpx.Client(timeout=10.0) as http:
        code = oauth.authorize(http, challenge, secrets.token_urlsafe(16))
        response = http.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CLIENT_REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": assertion,
            },
        )

    assert response.status_code == 200, response.text[:400]
    body = response.json()
    assert body.get("token_type", "").lower() == "bearer", body
    assert body.get("access_token"), body
