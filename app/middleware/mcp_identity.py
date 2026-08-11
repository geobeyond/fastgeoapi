"""Record which MCP client is talking to the server.

Without this a request to ``/mcp`` cannot be attributed to anyone. The
uvicorn access log carries no ``User-Agent``, and behind a reverse proxy
every request arrives from the proxy's address.
"""

from __future__ import annotations

import logging
from typing import Any

from fastmcp.server.middleware.middleware import Middleware

# A stdlib logger on purpose: the application intercepts stdlib logging
# into loguru, so this reaches the normal log stream, while tests can
# attach a handler to a known name and assert on it deterministically.
logger = logging.getLogger("fastgeoapi.mcp.client")

UNKNOWN = "unknown"


class MCPClientIdentityMiddleware(Middleware):
    """Log the declared identity of the client behind each MCP message.

    Hooked on ``on_message`` rather than ``on_initialize``: that hook
    exists on the base class but is never invoked for the protocol
    ``initialize`` in fastmcp 4+ — the handshake is served by the
    lower-level MCP server before the middleware chain runs. Verified
    against an in-memory server, so it is not an artefact of the stateless
    HTTP transport. The identity is still reachable afterwards, because
    the session keeps the initialize params for the whole of its life.

    What is deliberately *not* logged: tool arguments. Which tool ran is
    already visible from the upstream request line the MCP-to-pygeoapi
    hop emits, so recording arguments here would add privacy exposure
    without adding evidence.
    """

    async def on_message(self, context: Any, call_next: Any) -> Any:
        """Emit one line naming the client, then continue the chain."""
        name = version = protocol = UNKNOWN
        try:
            params = context.fastmcp_context.session.client_params
            info = params.client_info
            name = info.name or UNKNOWN
            version = info.version or UNKNOWN
            protocol = params.protocol_version or UNKNOWN
        except AttributeError:
            # No session yet, or a message shape without initialize params.
            # Never let observability break the request it observes.
            pass

        logger.info(
            "MCP %s from client=%s version=%s protocol=%s",
            getattr(context, "method", UNKNOWN) or UNKNOWN,
            name,
            version,
            protocol,
        )
        return await call_next(context)
