"""The authoring role: the same project, started differently.

ADR-0008 keeps this apart from the serving surface, and the separation
is by **entry point** rather than by a setting. A variable can be set by
mistake in production — it happened here with `PROD_` instead of `DEV_`,
and cost a deployment — while a CLI command is not something a
container's `CMD` reaches without someone rewriting it.

What it does not mount is as deliberate as what it does: no reload
webhook. Writing a configuration and putting it into service are two
powers, and holding both on one surface means whoever reaches it decides
what the server serves.
"""

from __future__ import annotations

import ipaddress
import secrets

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

#: Where the per-run secret travels. A header rather than a query
#: parameter for everything after the first load: query strings end up
#: in logs and in `Referer`. This is the header's *name*, not a secret —
#: the linters see "TOKEN" and assume the worst.
# ruff: ignore[hardcoded-password-string]
EDITOR_TOKEN_HEADER = "X-Fastgeoapi-Editor-Token"  # nosec B105


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def build_authoring_app(host: str = "127.0.0.1") -> Starlette:
    """Build the editor's application, refusing to be reachable.

    Parameters
    ----------
    host
        The address this is about to be served on. A non-loopback one
        raises: the authoring role has no authentication chain in front
        of it — demanding an OAuth flow to edit a file on one's own
        machine would be ceremony without security — so not being
        reachable from elsewhere is what stands in its place. That has
        to be enforced where it can still be enforced, at startup.

    Returns
    -------
        The application, carrying its per-run token on
        ``state.editor_token``.

    Notes
    -----
    The token is per **run**, not per request: an editor makes many
    calls, and a secret consumed on first use would let the page load
    and break everything after it. Loopback alone would not do — other
    pages share the browser — which is why every request carries it.
    """
    if not _is_loopback(host):
        raise ValueError(
            f"the configuration editor refuses to serve on '{host}': it has no "
            "authentication in front of it and must stay on loopback"
        )

    token = secrets.token_urlsafe(32)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def config(request: Request) -> JSONResponse:  # placeholder for Task 3
        return JSONResponse({"document": None})

    class TokenGuard(BaseHTTPMiddleware):
        """Every request carries the secret, not just the first one."""

        async def dispatch(self, request: Request, call_next):
            offered = request.headers.get(EDITOR_TOKEN_HEADER, "")
            if not secrets.compare_digest(offered, token):
                return JSONResponse({"message": "Unauthenticated"}, status_code=401)
            return await call_next(request)

    app = Starlette(
        routes=[
            Route("/editor/health", health, methods=["GET"]),
            Route("/editor/config", config, methods=["GET"]),
        ],
        middleware=[Middleware(TokenGuard)],
    )
    app.state.editor_token = token
    return app
