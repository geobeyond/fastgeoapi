"""Keep the advertised MCP tools in step with the configuration.

The tool list is generated from the OpenAPI document, which a config
reload rebuilds. Regenerating it used to mean restarting the process —
the limitation ADR-0003 declared — because the tools looked like a
fixed property of the server.

They are not. FastMCP 4 resolves `tools/list` by asking each of its
providers, on every request, so replacing the providers is enough. The
server object, its middleware, its auth and the mounted ASGI app with
its stateless session manager all stay exactly as they were, which is
what keeps this cheap: rebuilding the server instead would mean
re-entering its lifespan at runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx2
from fastmcp import FastMCP
from loguru import logger


def refresh_tools(
    server: FastMCP,
    openapi_spec: dict[str, Any],
    client: httpx2.AsyncClient,
    name: str = "OGC API MCP",
    cache_dir: Path | None = None,
) -> int:
    """Re-derive the tools of a live server from a new OpenAPI document.

    Parameters
    ----------
    server
        The running server whose providers are replaced in place.
    openapi_spec
        The document the tools are generated from.
    client
        The transport MCP reaches the API through — unchanged by a
        reload, so the same in-process client is reused.
    name
        Passed through to the throwaway server used to build the
        providers; it never reaches a client.
    cache_dir
        Where the resolver keeps the fetched OGC schemas. Passed in
        rather than read from the configuration, so this module stays
        independent of it — and out of an import cycle with `main`.

    Returns
    -------
        How many providers are now installed.

    Notes
    -----
    Clients are not notified. This version of FastMCP has no
    server-side `notifications/tools/list_changed`, and the stateless
    transport cannot push server-initiated messages by design, so a
    connected client keeps its cached list until it lists again —
    normally on reconnect. That is still a strict improvement on
    needing a restart of the process.
    """
    # The generated document carries external `$ref`s to the OGC schemas
    # and FastMCP resolves only local ones. `create_mcp_server` resolves
    # them at startup for the same reason; skipping it here left the
    # refresh raising "External or non-local reference not supported"
    # into the listener's error handler, so the reload looked fine and
    # the tools never moved.
    from app.utils.openapi_resolver import resolve_external_refs

    resolved = resolve_external_refs(openapi_spec, cache_dir=cache_dir)
    rebuilt = FastMCP.from_openapi(openapi_spec=resolved, client=client, name=name)
    # `providers` is a plain list on FastMCP 4.0.0b3 and not a declared
    # contract; tests/test_mcp_tool_refresh.py guards the shape so an
    # upgrade that changes it fails loudly instead of quietly refreshing
    # nothing. Slice assignment rather than rebinding: anything holding
    # a reference to the list keeps seeing the current providers.
    server.providers[:] = rebuilt.providers
    logger.info(
        f"MCP tools regenerated from the new configuration ({len(server.providers)} provider(s))"
    )
    return len(server.providers)
