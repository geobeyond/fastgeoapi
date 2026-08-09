"""End-to-end tests driven by fastmcp's own OAuth client implementation.

Every other end-to-end module drives the OAuth dance through
:class:`tests.mcp_e2e_client.MCPOAuthClient`, which walks each hop by
hand. That harness is deliberate — it is the only way to assert
intermediate state and to build the malformed clients the CIMD tests
need — but it shares a blind spot with everything built on it: it makes
*our* choices. A stock client makes fastmcp's.

When the two diverge, our suite stays green while real clients break.
That is not hypothetical: the CIMD default-scope regression passed every
test in this repository while Claude's connector was dead in production,
because our harness asked for scopes explicitly and a URL-identified
client inherits them instead.

So these tests give up all visibility into the individual hops and buy
one thing in exchange: the client code path is the one a third party
actually runs. Treat a failure here as "a stock client cannot talk to
us" — which is the whole interop question — and reach for the
hand-written harness to find out why.
"""

from __future__ import annotations

import portpicker
import pytest

from tests.mcp_e2e_client import cimd_document, headless_browser


@pytest.fixture
def fastgeoapi_env_extra() -> dict[str, str]:
    """Keep the consent interstitial in play.

    The headless browser has to clear fastmcp's consent form, CSRF
    double-submit included. Skipping it would make these tests pass
    against a configuration no deployment of ours uses.
    """
    return {"DEV_FASTGEOAPI_MCP_CONSENT_MODE": "remember"}


@pytest.mark.asyncio
async def test_stock_fastmcp_client_completes_the_dance_and_lists_tools(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
    monkeypatch,
):
    """A stock ``fastmcp.Client`` authenticates and lists tools.

    Discovery, dynamic registration, PKCE, the browser leg and the token
    exchange are all fastmcp's code here — the only thing standing in for
    a human is the redirect walk.
    """
    from fastmcp import Client
    from fastmcp.client.auth import OAuth

    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    mcp_url = f"{fastgeoapi_with_iam}/mcp/"

    with headless_browser(monkeypatch) as browser_errors:
        async with Client(mcp_url, auth=OAuth(mcp_url=mcp_url)) as client:
            tools = await client.list_tools()

    assert not browser_errors, f"the browser leg failed: {browser_errors[0]!r}"
    names = {tool.name for tool in tools}
    assert "getLandingPage" in names, sorted(names)


@pytest.mark.asyncio
async def test_stock_fastmcp_client_calls_a_tool(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
    monkeypatch,
):
    """Listing is not using: the token has to survive an actual call.

    Tool invocation crosses the MCP-to-pygeoapi hop, which listing never
    touches, so a token accepted at the protocol layer can still fail
    here.
    """
    from fastmcp import Client
    from fastmcp.client.auth import OAuth

    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    mcp_url = f"{fastgeoapi_with_iam}/mcp/"

    with headless_browser(monkeypatch) as browser_errors:
        async with Client(mcp_url, auth=OAuth(mcp_url=mcp_url)) as client:
            result = await client.call_tool("getLandingPage", {"f": "json"})

    assert not browser_errors, f"the browser leg failed: {browser_errors[0]!r}"
    assert result.content, "the landing page tool returned nothing"


@pytest.mark.asyncio
async def test_stock_fastmcp_client_identifies_by_cimd_url(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    iam_server,
    iam_oauth_client,
    monkeypatch,
):
    """A stock client identifying by CIMD URL, with no prior registration.

    This is the shape our first interop partner uses, and the one our
    hand-written CIMD tests cannot fully speak for: they build the
    URL-identified client themselves, so they attest that our server
    honours a document, not that a real client's use of ``client_id``
    metadata lines up with what our server expects.

    The document declares no ``scope``, which is how real ones are
    published — Claude's has no scope field, nor does the one our first
    interop partner put online — so the client inherits our authorization
    server's defaults. See the narrower-scope case below for why that
    detail is not incidental.

    The callback port is pinned because the document must declare the
    redirect URI up front and our server enforces it against the
    document — a client picking a random port cannot be described by a
    document written before it starts.
    """
    from fastmcp import Client
    from fastmcp.client.auth import OAuth

    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    callback_port = portpicker.pick_unused_port()
    client_id = serve_cimd_documents(
        cimd_document(
            redirect_uris=[f"http://localhost:{callback_port}/callback"],
            scope=None,
        )
    )

    mcp_url = f"{fastgeoapi_with_iam}/mcp/"
    auth = OAuth(
        mcp_url=mcp_url,
        client_metadata_url=client_id,
        callback_port=callback_port,
    )

    with headless_browser(monkeypatch) as browser_errors:
        async with Client(mcp_url, auth=auth) as client:
            tools = await client.list_tools()

    assert not browser_errors, f"the browser leg failed: {browser_errors[0]!r}"
    assert {tool.name for tool in tools}, "no tools advertised to the CIMD client"


@pytest.mark.asyncio
async def test_cimd_document_narrower_than_the_client_request_is_rejected(
    fastgeoapi_with_iam: str,
    serve_cimd_documents,
    iam_server,
    iam_oauth_client,
    monkeypatch,
):
    """A document declaring less than the client asks for fails the dance.

    Found by writing the test above, and worth pinning because the advice
    it invalidates is the natural one to give: "declare your scope
    explicitly instead of inheriting our defaults". A document saying
    ``openid`` is *narrower* than what a stock fastmcp client requests —
    it asks for ``offline_access`` too — and the authorization fails
    before the user sees anything.

    So an explicit scope is only safe when it covers what the client will
    request. This is the mirror image of the production regression where
    the server's defaults were narrowed instead of the document's.
    """
    from fastmcp import Client
    from fastmcp.client.auth import OAuth

    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    callback_port = portpicker.pick_unused_port()
    client_id = serve_cimd_documents(
        cimd_document(
            redirect_uris=[f"http://localhost:{callback_port}/callback"],
            scope="openid",
        )
    )

    mcp_url = f"{fastgeoapi_with_iam}/mcp/"
    auth = OAuth(
        mcp_url=mcp_url,
        client_metadata_url=client_id,
        callback_port=callback_port,
    )

    with headless_browser(monkeypatch), pytest.raises(RuntimeError, match="offline_access"):
        async with Client(mcp_url, auth=auth) as client:
            await client.list_tools()
