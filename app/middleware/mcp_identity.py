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


def _params_from_session(context: Any) -> Any | None:
    """Initialize params the session kept, or None if it kept none."""
    try:
        return context.fastmcp_context.session.client_params
    except AttributeError:
        return None


def _params_from_message(context: Any) -> Any | None:
    """Initialize params carried by the message currently in flight.

    Only an ``initialize`` message has them, and the middleware chain
    receives it as either the request or its params depending on the
    transport, so both shapes are tried.
    """
    message = getattr(context, "message", None)
    if message is None:
        return None
    params = getattr(message, "params", message)
    return params if hasattr(params, "client_info") else None


class MCPClientIdentityMiddleware(Middleware):
    """Log the declared identity of the client behind each MCP message.

    Two sources, because one alone covers only half the deployments.

    Under the sessionless protocol (``2026-07-28``) the session keeps the
    client's initialize params for its whole life, so any message can be
    attributed. Under the older handshake — which is what Claude Desktop
    still negotiates — combined with our stateless HTTP transport, every
    request builds a fresh session that never saw an ``initialize``, and
    the session holds nothing. There the identity exists exactly once, in
    the ``initialize`` message itself, so that message is read directly.

    The consequence is worth stating plainly: on the older handshake we
    can name the client when it connects, and only then. Subsequent calls
    are correlated by time. That is a property of a stateless server
    talking a session-oriented protocol, not something this middleware
    can recover.

    What is deliberately *not* logged: tool arguments. Which tool ran is
    already visible from the upstream request line the MCP-to-pygeoapi
    hop emits, so recording arguments here would add privacy exposure
    without adding evidence.
    """

    async def on_message(self, context: Any, call_next: Any) -> Any:
        """Emit one line naming the client, then continue the chain."""
        params = _params_from_session(context) or _params_from_message(context)

        name = version = protocol = UNKNOWN
        info = getattr(params, "client_info", None)
        if info is not None:
            name = getattr(info, "name", None) or UNKNOWN
            version = getattr(info, "version", None) or UNKNOWN
            protocol = getattr(params, "protocol_version", None) or UNKNOWN

        logger.info(
            "MCP %s from client=%s version=%s protocol=%s",
            getattr(context, "method", UNKNOWN) or UNKNOWN,
            name,
            version,
            protocol,
        )
        return await call_next(context)
