"""End-to-end coverage of the access-token lifetime and refresh grant.

These tests pin the half of the token lifecycle that is ours. A client
like Claude refreshes on its own schedule and no test of ours can fix
that behaviour; what we *can* guarantee is that the authorization server
issues a refresh token, honours the configured client-facing lifetime,
and accepts the refresh grant.

That guarantee is exactly what was missing in production on 2026-08-07.
The upstream IdP was returning no refresh token, so fastmcp silently
capped the client-facing lifetime at the upstream ``expires_in`` — one
hour instead of the configured week. The connector kept reporting
"connected" and served an empty tool list after every expiry, and the
configuration looked correct the whole time because the cap leaves no
trace in it. The suite could not have caught it: the canaille client the
harness registers is not allowed to grant ``offline_access``, so every
existing test runs in precisely the capped condition without asserting
anything about it.

So both sides are covered here: the cap when no refresh token is issued,
and the full lifetime plus working refresh grant when one is.
"""

from __future__ import annotations

import httpx
import pytest

from tests.mcp_e2e_client import MCPOAuthClient, authenticated_mcp_client

# Deliberately longer than any upstream access-token lifetime an IdP is
# likely to hand out. The cap is `min(configured, upstream)`, so a value
# below the upstream lifetime is indistinguishable from an uncapped one
# and the assertions below would pass with the defect present. Two hours
# was not enough: canaille issues longer-lived tokens than Logto's hour,
# and the capped case came back looking healthy.
CONFIGURED_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


@pytest.fixture
def fastgeoapi_env_extra() -> dict[str, str]:
    """Ask for a client-facing lifetime the upstream IdP would never set."""
    return {"DEV_FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS": str(CONFIGURED_TTL_SECONDS)}


def _authenticated(
    base_url: str, iam_server, iam_oauth_client
) -> tuple[MCPOAuthClient, httpx.Client]:
    """Log the user in and run the dance, returning the client and session."""
    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    http = httpx.Client(timeout=10.0)
    oauth = MCPOAuthClient(base_url=base_url, scope="openid profile email offline_access")
    oauth.run_dance(http)
    return oauth, http


def test_refresh_token_is_issued_and_lifetime_is_honoured(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
):
    """With ``offline_access`` granted, the configured lifetime survives.

    The two assertions are one finding: a refresh token means fastmcp has
    no reason to cap, and the absence of a cap is what makes the
    configured value observable.
    """
    oauth, http = _authenticated(fastgeoapi_with_iam, iam_server, iam_oauth_client)
    try:
        assert oauth.refresh_token, (
            "the IdP issued no refresh token; the client-facing token lifetime "
            "is silently capped at the upstream expires_in whenever this happens"
        )

        response = http.post(
            f"{fastgeoapi_with_iam}/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": oauth.refresh_token,
                "client_id": oauth.client_id,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["expires_in"] == CONFIGURED_TTL_SECONDS
    finally:
        http.close()


@pytest.mark.asyncio
async def test_refreshed_token_is_accepted_by_the_mcp_server(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
):
    """A token obtained through the refresh grant works on /mcp.

    Issuing a new token is not the contract — the contract is that the
    MCP server accepts it. The two live in different stores (JWT, JTI
    mapping, upstream token) and a refresh that updated only some of them
    would still return 200 here at the token endpoint while failing every
    subsequent tool call.
    """
    oauth, http = _authenticated(fastgeoapi_with_iam, iam_server, iam_oauth_client)
    try:
        first_token = oauth.access_token
        assert oauth.refresh(http).status_code == 200
        assert oauth.access_token != first_token, "refresh returned the same token"
    finally:
        http.close()

    async with authenticated_mcp_client(fastgeoapi_with_iam, oauth=oauth) as client:
        tools = await client.list_tools()
        assert tools, "no tools available with the refreshed token"


def test_refresh_tokens_are_one_time_use(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
):
    """Rotation: a redeemed refresh token cannot be redeemed twice."""
    oauth, http = _authenticated(fastgeoapi_with_iam, iam_server, iam_oauth_client)
    try:
        spent = oauth.refresh_token
        assert oauth.refresh(http).status_code == 200
        assert oauth.refresh_token != spent, "refresh token was not rotated"

        replayed = http.post(
            f"{fastgeoapi_with_iam}/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": spent,
                "client_id": oauth.client_id,
            },
        )
        # RFC 6749 §5.2 assigns 400 to `invalid_grant` and reserves 401
        # for client-authentication failures; fastmcp answers 401 here.
        # The rejection is what protects us, so the status code is
        # accepted loosely and tracked as an upstream item rather than
        # pinned to the wrong value.
        assert replayed.status_code in (400, 401), replayed.text
        assert replayed.json()["error"] == "invalid_grant", replayed.text
    finally:
        http.close()


class TestWithoutUpstreamRefreshToken:
    """The capped case — the production defect, pinned.

    Nothing here is desirable behaviour; the cap itself is sound (a
    reference token must not outlive the upstream token it points at when
    there is no way to renew it). What these tests hold in place is that
    the cap stays *observable*, so a future upstream change is noticed
    here rather than in a connector that quietly stops listing tools.
    """

    @pytest.fixture
    def iam_client_grant_types(self) -> list[str]:
        """Forbid the refresh grant, so the IdP issues no refresh token.

        Withholding the ``offline_access`` scope would *not* do it:
        authlib keys refresh-token issuance off the grant types, and
        canaille hands one back regardless of the scope. Getting this
        wrong is how the condition stayed untested for so long.
        """
        return ["authorization_code"]

    def test_no_refresh_token_caps_the_configured_lifetime(
        self,
        fastgeoapi_with_iam: str,
        iam_server,
        iam_oauth_client,
    ):
        """Without a refresh token the configured lifetime is ignored."""
        user = iam_server.random_user()
        iam_server.login(user)
        iam_server.consent(user, iam_oauth_client)

        http = httpx.Client(timeout=10.0)
        try:
            oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam)
            oauth.register_via_dcr(http)
            from tests.mcp_e2e_client import pkce_pair

            verifier, challenge = pkce_pair()
            code = oauth.authorize(http, challenge, "no-upstream-refresh")

            response = http.post(
                f"{fastgeoapi_with_iam}/mcp/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": oauth.redirect_uri,
                    "client_id": oauth.client_id,
                    "code_verifier": verifier,
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()

            assert "refresh_token" not in body
            assert body["expires_in"] < CONFIGURED_TTL_SECONDS, (
                "the configured lifetime was applied without a refresh token to "
                "back it; either the IdP started issuing one or the cap is gone"
            )
        finally:
            http.close()
