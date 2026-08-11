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
