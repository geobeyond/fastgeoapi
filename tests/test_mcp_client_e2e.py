"""End-to-end MCP client tests: the interop path, exercised by our suite.

Where ``test_mcp_oauth_e2e`` asserts each OAuth hop, these tests act as
an **MCP client**: obtain a token from the authorization server this
server advertises, then speak real Streamable HTTP MCP over the network
and call tools — the shape of an OpenID AIIM interoperability test for
the "MCP Server" and "Resource OAuth AS" roles.

Both tests use the ``fastgeoapi_with_iam`` fixture (a live instance
backed by a local canaille IdP) and the shared harness in
:mod:`tests.mcp_e2e_client`.
"""

from __future__ import annotations

import httpx
import pytest

from tests.mcp_e2e_client import MCPOAuthClient, authenticated_mcp_client


@pytest.mark.asyncio
async def test_mcp_client_lists_and_calls_tools_over_http(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
):
    """A real MCP client authenticates, lists tools and calls one.

    This is the end-to-end contract an interop partner exercises: the
    token minted by our authorization server is accepted by our MCP
    server, and the generated OGC API tools answer over the wire.
    """
    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    async with authenticated_mcp_client(fastgeoapi_with_iam) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert names, "no tools advertised"
        assert "getCollections" in names, sorted(names)

        result = await client.call_tool("getCollections", {})

    structured = result.structured_content or {}
    payload = structured.get("result", structured)
    collection_ids = {collection["id"] for collection in payload.get("collections", [])}
    assert {"lakes", "obs"} <= collection_ids, collection_ids


def test_oauth_protected_resource_metadata_drives_discovery(fastgeoapi_with_iam: str):
    """The RFC 9728 discovery chain a client follows must be self-consistent.

    An MCP client with no configuration must be able to: hit the MCP
    endpoint, read the ``resource_metadata`` URL out of the 401
    challenge, fetch it, find the authorization server, and fetch that
    server's RFC 8414 metadata. This is the "OPRM" row of the interop
    matrix — the single row that qualifies the MCP Server role.
    """
    base_url = fastgeoapi_with_iam

    with httpx.Client(timeout=10.0) as http:
        unauthenticated = http.post(
            f"{base_url}/mcp/",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert unauthenticated.status_code == 401
        challenge = unauthenticated.headers.get("www-authenticate", "")

        # The challenge must carry the pointer, not just the realm.
        assert "resource_metadata=" in challenge, challenge
        metadata_url = challenge.split('resource_metadata="', 1)[1].split('"', 1)[0]

        prm = http.get(metadata_url)
        assert prm.status_code == 200, prm.text[:200]
        prm_body = prm.json()
        assert prm_body["resource"].rstrip("/") == f"{base_url}/mcp", prm_body
        authorization_servers = prm_body.get("authorization_servers") or []
        assert authorization_servers, prm_body

        # RFC 8414: metadata lives under the well-known path built from the
        # issuer, and must describe an authorization server that can mint
        # tokens for this resource.
        issuer = authorization_servers[0].rstrip("/")
        issuer_path = issuer.removeprefix(base_url)
        as_metadata = http.get(f"{base_url}/.well-known/oauth-authorization-server{issuer_path}")
        assert as_metadata.status_code == 200, as_metadata.text[:200]
        as_body = as_metadata.json()
        assert as_body["issuer"].rstrip("/") == issuer, as_body
        assert "authorization_code" in as_body["grant_types_supported"], as_body
        assert "S256" in as_body["code_challenge_methods_supported"], as_body


@pytest.mark.asyncio
async def test_reusing_the_harness_token_avoids_a_second_dance(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
):
    """The harness can hand its token to a second client session.

    Interop tests often need several MCP sessions against one
    authorization: the stateless transport plus a cached token must make
    that work without re-running the browser dance.
    """
    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam)
    oauth.run_dance()
    assert oauth.access_token

    for _ in range(2):
        async with authenticated_mcp_client(fastgeoapi_with_iam, oauth=oauth) as client:
            tools = await client.list_tools()
            assert tools
