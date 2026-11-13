"""A token marked as an ID-JAG grant is refused when EMA is not configured.

The OAuth proxy signs the access tokens it hands to MCP clients. Those
from an ID-JAG exchange carry ``fastmcp_grant: "id_jag"`` and are taken
as the identity, with no upstream token behind them. FastMCP 4.0.3 took
them even with no trusted issuer configured, so whoever held the signing
key could act as any user (PrefectHQ/fastmcp#5115, fixed in 4.0.4).
``configure_mcp_auth`` passes no ``jwt_signing_key``, so FastMCP derives
the key from the IdP client secret.
"""

from unittest.mock import MagicMock, patch

import pytest

OIDC_CONFIG = {
    "issuer": "https://example.logto.app/oidc",
    "authorization_endpoint": "https://example.logto.app/oidc/auth",
    "token_endpoint": "https://example.logto.app/oidc/token",
    "jwks_uri": "https://example.logto.app/oidc/jwks",
    "response_types_supported": ["code"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
}


def _proxy():
    from app.auth.mcp_auth_provider import configure_mcp_auth

    response = MagicMock()
    response.json.return_value = OIDC_CONFIG
    response.raise_for_status = MagicMock()
    with patch("fastmcp.server.auth.oidc_proxy.httpx2.get", return_value=response):
        auth, _ = configure_mcp_auth(
            oidc_well_known_endpoint="https://example.logto.app/oidc/.well-known/openid-configuration",
            client_id="test-client-id",
            client_secret="test-client-secret",
            mcp_base_url="http://localhost:5000/mcp/",
        )
    return auth


@pytest.mark.asyncio
async def test_a_token_forged_as_an_id_jag_grant_is_refused_without_trusted_issuers():
    auth = _proxy()
    forged = auth.jwt_issuer.issue_access_token(
        client_id="forged",
        scopes=["openid"],
        jti="forged-1",
        subject="attacker",
        extra_claims={"fastmcp_grant": "id_jag", "email": "victim@example.com"},
    )

    assert await auth.load_access_token(forged) is None
