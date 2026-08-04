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
from typing import Any

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
    """Serve CIMD documents and remote key sets in-process.

    Every SSRF-guarded hop is replaced against one registry: the CIMD
    document fetch (``cimd.ssrf_safe_fetch_response``), the ``jwks_uri``
    pre-validation the document check performs (``cimd.validate_url``),
    and the remote JWKS fetch itself (``providers.jwt.ssrf_safe_fetch``).
    Unpublished URLs raise the same errors the real guards would.

    Returns a callable that publishes a payload at a URL (defaulting to
    the document's own ``client_id``).
    """
    from fastmcp.server.auth import cimd as cimd_module
    from fastmcp.server.auth.providers import jwt as jwt_module
    from fastmcp.server.auth.ssrf import SSRFError, SSRFFetchError, SSRFFetchResponse

    published: dict[str, dict] = {}

    async def fake_fetch_response(url: str, **_kwargs) -> SSRFFetchResponse:
        if url not in published:
            raise SSRFFetchError(f"nothing published at {url}")
        return SSRFFetchResponse(
            content=json.dumps(published[url]).encode(),
            status_code=200,
            # No caching: each test gets its own document for the same URL.
            headers={"Cache-Control": "no-store"},
        )

    async def fake_fetch_bytes(url: str, **_kwargs) -> bytes:
        if url not in published:
            raise SSRFFetchError(f"nothing published at {url}")
        return json.dumps(published[url]).encode()

    async def fake_validate_url(url: str, **_kwargs) -> None:
        """Accept published test URLs in the document's own jwks_uri check."""
        if url not in published:
            raise SSRFError(f"nothing published at {url}")

    monkeypatch.setattr(cimd_module, "ssrf_safe_fetch_response", fake_fetch_response)
    monkeypatch.setattr(cimd_module, "validate_url", fake_validate_url)
    monkeypatch.setattr(jwt_module, "ssrf_safe_fetch", fake_fetch_bytes)

    def publish(payload: dict, at: str | None = None) -> str:
        """Publish a payload, optionally at a URL other than its client_id."""
        url = at or str(payload["client_id"])
        published[url] = payload
        return url

    return publish


def signing_key(kid: str = "cimd-e2e") -> tuple[Any, dict]:
    """Return an RSA key and its public JWK, ready for a document."""
    key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
    return key, key.as_dict(is_private=False, alg="RS256", use="sig", kid=kid)


def client_assertion(key, kid: str, client_id: str, token_endpoint: str) -> str:
    """Sign an RFC 7523 client assertion for ``private_key_jwt``.

    The audience is the token endpoint the authorization server
    advertises: a conforming client has no other value to sign.
    """
    now = int(time.time())
    return jwt.encode(
        {"alg": "RS256", "kid": kid, "typ": "JWT"},
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


def advertised_token_endpoint(base_url: str) -> str:
    """Read the token endpoint out of the authorization server metadata."""
    metadata = httpx.get(f"{base_url}/.well-known/oauth-authorization-server/mcp").json()
    return metadata["token_endpoint"]


def exchange_with_assertion(base_url: str, oauth: MCPOAuthClient, assertion: str) -> httpx.Response:
    """Authorize, then exchange the code using a client assertion."""
    verifier, challenge = pkce_pair()
    with httpx.Client(timeout=10.0) as http:
        code = oauth.authorize(http, challenge, secrets.token_urlsafe(16))
        return http.post(
            advertised_token_endpoint(base_url),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": CLIENT_REDIRECT_URI,
                "client_id": oauth.client_id,
                "code_verifier": verifier,
                "client_assertion_type": ASSERTION_TYPE,
                "client_assertion": assertion,
            },
        )


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


def test_cimd_private_key_jwt_with_inline_jwks(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    logged_in_user,
):
    """``private_key_jwt`` with the key published inline in the document.

    Matrix row: *Authorization code grant with PKCE / JWT*. The client
    proves possession of the key in its own metadata document instead of
    presenting a secret.
    """
    key, public_jwk = signing_key()
    client_id = serve_cimd_documents(
        cimd_document(
            token_endpoint_auth_method="private_key_jwt",
            jwks={"keys": [public_jwk]},
        )
    )

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam, client_id=client_id, scope=CIMD_SCOPE)
    assertion = client_assertion(
        key, "cimd-e2e", client_id, advertised_token_endpoint(fastgeoapi_with_iam)
    )
    response = exchange_with_assertion(fastgeoapi_with_iam, oauth, assertion)

    assert response.status_code == 200, response.text[:400]
    body = response.json()
    assert body.get("token_type", "").lower() == "bearer", body
    assert body.get("access_token"), body


@pytest.mark.asyncio
async def test_cimd_private_key_jwt_with_remote_jwks_uri(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    logged_in_user,
):
    """``private_key_jwt`` with keys fetched from the document's ``jwks_uri``.

    The remote variant of the same matrix row, and the realistic one:
    clients rotate keys by republishing a key set rather than editing
    their metadata document. The fetch goes through a second SSRF-guarded
    path, so this exercises code the inline variant never touches. The
    resulting token is then used on a real MCP session.
    """
    from tests.mcp_e2e_client import authenticated_mcp_client

    key, public_jwk = signing_key(kid="cimd-remote")
    jwks_uri = f"https://clients.example.test/keys/{secrets.token_hex(6)}.json"
    serve_cimd_documents({"keys": [public_jwk]}, at=jwks_uri)
    client_id = serve_cimd_documents(
        cimd_document(
            token_endpoint_auth_method="private_key_jwt",
            jwks_uri=jwks_uri,
        )
    )

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam, client_id=client_id, scope=CIMD_SCOPE)
    assertion = client_assertion(
        key, "cimd-remote", client_id, advertised_token_endpoint(fastgeoapi_with_iam)
    )
    response = exchange_with_assertion(fastgeoapi_with_iam, oauth, assertion)

    assert response.status_code == 200, response.text[:400]
    oauth.access_token = response.json()["access_token"]

    async with authenticated_mcp_client(fastgeoapi_with_iam, oauth=oauth) as client:
        assert await client.list_tools()


def test_cimd_assertion_signed_with_an_unpublished_key_is_rejected(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    logged_in_user,
):
    """A key that is not in the document's key set must not authenticate.

    Key-based client authentication is only worth a matrix checkmark if
    it is *enforced*: possession of any key must not do — it has to be a
    key the client published.
    """
    _published_key, public_jwk = signing_key(kid="cimd-published")
    attacker_key, _attacker_jwk = signing_key(kid="cimd-published")
    client_id = serve_cimd_documents(
        cimd_document(
            token_endpoint_auth_method="private_key_jwt",
            jwks={"keys": [public_jwk]},
        )
    )

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam, client_id=client_id, scope=CIMD_SCOPE)
    # Same kid, different key material.
    assertion = client_assertion(
        attacker_key, "cimd-published", client_id, advertised_token_endpoint(fastgeoapi_with_iam)
    )
    response = exchange_with_assertion(fastgeoapi_with_iam, oauth, assertion)

    assert response.status_code >= 400, response.text[:300]
    assert "access_token" not in response.text, response.text[:300]
