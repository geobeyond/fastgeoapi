"""End-to-end EMA tests: the enterprise IdP decides, our AS honours it.

Enterprise-Managed Authorization
([extension](https://modelcontextprotocol.io/extensions/auth/enterprise-managed-authorization),
SEP-990) moves the access decision from the end user to the
organisation's identity provider. The client obtains an **ID-JAG**
(Identity Assertion JWT Authorization Grant) from its own enterprise
IdP, then exchanges it at *our* token endpoint for an access token —
no browser, no consent screen, no per-user authorisation of every
third-party MCP server.

In the OpenID AIIM interoperability program fastgeoapi is a
"third-party MCP server that requires its own OAuth authorization
server", which places us at the receiving end of that exchange. These
tests cover what the program's EMA matrix asks our role to verify:

- *Valid ID-JAG* — signature, trusted issuer, ``aud``, ``typ``, and
  that the assertion's signed ``client_id`` matches the authenticated
  client
- *resource support* — the issued token is bound to the MCP server the
  assertion names

The enterprise IdP is played by pytest-iam: we sign assertions with a
key it publishes, so the signature is verified against a real remote
JWKS rather than a stub.
"""

from __future__ import annotations

import secrets
import time

import httpx
import pytest

ID_JAG_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"

# SEP-990 §5.1. Note the `+jwt` suffix: the AIIM event document writes
# `oauth-id-jag-jwt`, which does not match the SEP or any implementation
# we have seen — raised with the CG.
ID_JAG_TYP = "oauth-id-jag+jwt"


@pytest.fixture
def fastgeoapi_env_extra(ema_issuer) -> dict[str, str]:
    """Trust the throwaway enterprise IdP for the whole module."""
    return {"DEV_FASTGEOAPI_MCP_TRUSTED_ISSUERS": ema_issuer.issuer}


def id_jag(
    *,
    issuer: str,
    audience: str,
    client_id: str,
    resource: str,
    signing_key,
    kid: str,
    subject: str = "employee@partner-corp.example",
    typ: str = ID_JAG_TYP,
    scope: str = "openid profile email",
    **overrides,
) -> str:
    """Sign an ID-JAG the way an enterprise IdP would issue one."""
    from authlib.jose import jwt

    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "client_id": client_id,
        "resource": resource,
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + 300,
        # The IdP states what the employee may do; the token minted from
        # this assertion inherits it (the "scope support" row of the EMA
        # matrix). Without it the resource server rightly answers
        # insufficient_scope.
        "scope": scope,
    }
    claims.update(overrides)
    return jwt.encode({"alg": "RS256", "kid": kid, "typ": typ}, claims, signing_key).decode()


def exchange_id_jag(base_url: str, assertion: str, client_id: str) -> httpx.Response:
    """Present an ID-JAG at the token endpoint, as an EMA client does."""
    with httpx.Client(timeout=10.0) as http:
        metadata = http.get(f"{base_url}/.well-known/oauth-authorization-server/mcp").json()
        return http.post(
            metadata["token_endpoint"],
            data={
                "grant_type": ID_JAG_GRANT,
                "assertion": assertion,
                "client_id": client_id,
            },
        )


def test_metadata_advertises_the_id_jag_grant_profile(fastgeoapi_with_ema: str):
    """A client discovers EMA support before attempting the exchange.

    The authorization server metadata must announce both the grant and
    the ``id-jag`` profile — otherwise an EMA-capable client has no way
    to know it can skip the browser flow.
    """
    metadata = httpx.get(f"{fastgeoapi_with_ema}/.well-known/oauth-authorization-server/mcp").json()

    assert ID_JAG_GRANT in metadata.get("grant_types_supported", []), metadata
    profiles = metadata.get("authorization_grant_profiles_supported", [])
    assert "urn:ietf:params:oauth:grant-profile:id-jag" in profiles, metadata


def test_id_jag_is_exchanged_for_an_access_token(
    fastgeoapi_with_ema: str,
    ema_issuer,
    ema_client_id: str,
):
    """The happy path: a valid ID-JAG yields a usable access token.

    This is the *Valid ID-JAG* row of the interop matrix — the single
    row that qualifies the EMA column.
    """
    assertion = id_jag(
        issuer=ema_issuer.issuer,
        audience=f"{fastgeoapi_with_ema}/mcp/",
        client_id=ema_client_id,
        resource=f"{fastgeoapi_with_ema}/mcp/",
        signing_key=ema_issuer.key,
        kid=ema_issuer.kid,
    )

    response = exchange_id_jag(fastgeoapi_with_ema, assertion, ema_client_id)

    assert response.status_code == 200, response.text[:400]
    body = response.json()
    assert body.get("access_token"), body
    assert body.get("token_type", "").lower() == "bearer", body
    # EMA clients re-exchange rather than refresh: the assertion is the
    # renewable credential, held by the client and revocable at the IdP.
    assert "refresh_token" not in body, body


@pytest.mark.asyncio
async def test_token_from_id_jag_is_accepted_by_the_mcp_server(
    fastgeoapi_with_ema: str,
    ema_issuer,
    ema_client_id: str,
):
    """The whole point: the minted token actually opens the MCP server.

    An access token that no MCP session accepts would satisfy the
    letter of the exchange and none of its purpose.
    """
    from fastmcp import Client
    from fastmcp.client.auth import BearerAuth
    from fastmcp.client.transports import StreamableHttpTransport

    assertion = id_jag(
        issuer=ema_issuer.issuer,
        audience=f"{fastgeoapi_with_ema}/mcp/",
        client_id=ema_client_id,
        resource=f"{fastgeoapi_with_ema}/mcp/",
        signing_key=ema_issuer.key,
        kid=ema_issuer.kid,
    )
    token = exchange_id_jag(fastgeoapi_with_ema, assertion, ema_client_id).json()["access_token"]

    transport = StreamableHttpTransport(url=f"{fastgeoapi_with_ema}/mcp/", auth=BearerAuth(token))
    async with Client(transport) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools}, "no tools reachable with an EMA-issued token"


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("untrusted issuer", {"issuer": "https://attacker.example"}),
        ("wrong audience", {"audience": "https://someone-else.example/mcp/"}),
        ("mismatched client_id", {"client_id": "https://another-client.example/cimd.json"}),
        ("wrong typ", {"typ": "JWT"}),
        ("resource for another server", {"resource": "https://other-mcp.example/mcp/"}),
    ],
)
def test_invalid_id_jag_is_refused(
    fastgeoapi_with_ema: str,
    ema_issuer,
    ema_client_id: str,
    label: str,
    overrides: dict,
):
    """Each binding in the assertion must actually be enforced.

    An assertion is a bearer credential minted by someone else: if any
    of issuer, audience, client binding, type or resource can be forged
    or ignored, the grant becomes a way to mint tokens for servers and
    clients the IdP never authorised.
    """
    args = {
        "issuer": ema_issuer.issuer,
        "audience": f"{fastgeoapi_with_ema}/mcp/",
        "client_id": ema_client_id,
        "resource": f"{fastgeoapi_with_ema}/mcp/",
        "signing_key": ema_issuer.key,
        "kid": ema_issuer.kid,
    }
    args.update(overrides)
    # The client_id sent in the request stays the authenticated one: the
    # mismatch case must be caught by the signed claim, not by the form.
    assertion = id_jag(**args)

    response = exchange_id_jag(fastgeoapi_with_ema, assertion, ema_client_id)

    assert response.status_code >= 400, f"{label}: {response.text[:300]}"
    assert "access_token" not in response.text, f"{label}: {response.text[:300]}"


def test_replayed_id_jag_is_refused(
    fastgeoapi_with_ema: str,
    ema_issuer,
    ema_client_id: str,
):
    """A captured assertion must not be reusable.

    ``jti`` replay protection is what keeps an intercepted ID-JAG from
    becoming an unlimited token dispenser for its whole lifetime.
    """
    assertion = id_jag(
        issuer=ema_issuer.issuer,
        audience=f"{fastgeoapi_with_ema}/mcp/",
        client_id=ema_client_id,
        resource=f"{fastgeoapi_with_ema}/mcp/",
        signing_key=ema_issuer.key,
        kid=ema_issuer.kid,
    )

    first = exchange_id_jag(fastgeoapi_with_ema, assertion, ema_client_id)
    assert first.status_code == 200, first.text[:300]

    replay = exchange_id_jag(fastgeoapi_with_ema, assertion, ema_client_id)
    assert replay.status_code >= 400, replay.text[:300]
    assert "access_token" not in replay.text, replay.text[:300]
