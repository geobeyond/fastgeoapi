"""The server records which client connected.

Without this, a request to the MCP endpoint is unattributable. The access
log carries no User-Agent, and behind a reverse proxy every request
arrives from the proxy's address.
"""

from __future__ import annotations

import logging

import pytest

from tests.mcp_e2e_client import headless_browser

CLIENT_NAME = "interop-probe"
CLIENT_VERSION = "9.9.9"

MIDDLEWARE_LOGGER = "fastgeoapi.mcp.client"


@pytest.fixture
def fastgeoapi_env_extra() -> dict[str, str]:
    """Keep the consent interstitial in play, as in a real deployment."""
    return {"DEV_FASTGEOAPI_MCP_CONSENT_MODE": "remember"}


@pytest.fixture
def captured_middleware_logs():
    """Collect records from the MCP middleware logger.

    A dedicated handler rather than ``caplog``: the server runs in a
    uvicorn thread and our logging setup rebinds handlers at import, so
    capturing on the specific logger is the deterministic option.
    """
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    logger = logging.getLogger(MIDDLEWARE_LOGGER)
    handler = _Collector(level=logging.DEBUG)
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


@pytest.mark.asyncio
async def test_client_identity_reaches_the_logs(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
    captured_middleware_logs,
    monkeypatch,
):
    """The name a client declares for itself reaches the logs.

    It is read from the session's stored `initialize` params on each
    message, not from the handshake itself: fastmcp's `on_initialize`
    hook is never invoked for the protocol handshake, which is served
    below the middleware chain.
    """
    from fastmcp import Client
    from fastmcp.client.auth import OAuth
    from mcp.types import Implementation

    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    mcp_url = f"{fastgeoapi_with_iam}/mcp/"

    with headless_browser(monkeypatch) as browser_errors:
        async with Client(
            mcp_url,
            auth=OAuth(mcp_url=mcp_url),
            client_info=Implementation(name=CLIENT_NAME, version=CLIENT_VERSION),
        ) as client:
            await client.list_tools()

    assert not browser_errors, f"the browser leg failed: {browser_errors[0]!r}"

    logged = "\n".join(record.getMessage() for record in captured_middleware_logs)
    assert CLIENT_NAME in logged, (
        "the client's declared name is absent from the logs, so a request "
        f"cannot be attributed to it. Captured:\n{logged or '(nothing)'}"
    )


def test_identity_is_recorded_on_the_legacy_handshake(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
    captured_middleware_logs,
):
    """A client on the pre-sessionless protocol is still named.

    This is the case that matters in production and the one a stock
    fastmcp client cannot exercise: it negotiates `2026-07-28`, where the
    session retains the initialize params so any message can be
    attributed. Claude Desktop negotiates `2025-11-25`, and against our
    stateless transport every request builds a session that never saw an
    `initialize` — so the identity has to be read from that message
    itself, or everything logs as `unknown`.

    It did log as `unknown`, in production, while this module's other
    tests passed. Hence the raw handshake here rather than a client
    library: the protocol version is the variable under test, and no
    client we have on hand speaks the old one.
    """
    import httpx

    from tests.mcp_e2e_client import MCPOAuthClient

    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    oauth = MCPOAuthClient(base_url=fastgeoapi_with_iam)
    token = oauth.run_dance()

    response = httpx.post(
        f"{fastgeoapi_with_iam}/mcp/",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        },
        timeout=15.0,
    )
    assert response.status_code == 200, response.text[:300]

    logged = "\n".join(record.getMessage() for record in captured_middleware_logs)
    assert CLIENT_NAME in logged, (
        "a client on the legacy handshake logged as unknown — the identity "
        f"was not read from the initialize message. Captured:\n{logged or '(nothing)'}"
    )


@pytest.mark.asyncio
async def test_tool_arguments_are_not_logged(
    fastgeoapi_with_iam: str,
    iam_server,
    iam_oauth_client,
    captured_middleware_logs,
    monkeypatch,
):
    """Identity is recorded; what the tool was given is not.

    We log the MCP method, never the params. Which tool ran is already
    visible from the request line the MCP-to-pygeoapi hop emits, so
    recording arguments here would add privacy exposure without adding
    evidence — and it would arrive as a side effect of wanting to know
    who connected, which is the wrong way to make that decision.
    """
    from fastmcp import Client
    from fastmcp.client.auth import OAuth
    from mcp.types import Implementation

    user = iam_server.random_user()
    iam_server.login(user)
    iam_server.consent(user, iam_oauth_client)

    mcp_url = f"{fastgeoapi_with_iam}/mcp/"

    with headless_browser(monkeypatch) as browser_errors:
        async with Client(
            mcp_url,
            auth=OAuth(mcp_url=mcp_url),
            client_info=Implementation(name=CLIENT_NAME, version=CLIENT_VERSION),
        ) as client:
            await client.call_tool("getLandingPage", {"f": "json"})

    assert not browser_errors, f"the browser leg failed: {browser_errors[0]!r}"

    logged = "\n".join(record.getMessage() for record in captured_middleware_logs)
    assert CLIENT_NAME in logged, "identity should still be recorded"
    assert "getLandingPage" not in logged, (
        f"tool params reached the logs; only the method should:\n{logged}"
    )
