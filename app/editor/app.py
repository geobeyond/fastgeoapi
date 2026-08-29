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
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.editor.routes import build_routes

#: Where the per-run secret travels. A header rather than a query
#: parameter for everything after the first load: query strings end up
#: in logs and in `Referer`. This is the header's *name*, not a secret —
#: the linters see "TOKEN" and assume the worst.
# ruff: ignore[hardcoded-password-string]
EDITOR_TOKEN_HEADER = "X-Fastgeoapi-Editor-Token"  # nosec B105

#: Where the same secret travels once a browser is holding it. A page
#: cannot send a header before it has the token, and the only way to
#: give it one through an address is to put the secret in the address —
#: where it outlives the session, in history and in `Referer`. So the
#: page asks for it, posts it once, and is given this instead.
#:
#: A cookie also *confines*: the browser binds it to the origin that set
#: it, so it cannot be sent to the deployment even by mistake. The header
#: has no such limit. Name, not secret.
# ruff: ignore[hardcoded-password-string]
EDITOR_TOKEN_COOKIE = "fastgeoapi_editor_token"  # nosec B105


def _is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


#: Where the compiled page lands. Sources live in `frontend/`; Vite
#: writes here, CI builds it, and the wheel ships it as package data.
DEFAULT_PAGE = Path(__file__).parent / "static"

_NOT_BUILT = (
    "The editor's page has not been compiled into this installation.\n\n"
    "The API is working and usable without it — that is why it came\n"
    "first. To get the page as well:\n\n"
    "    cd frontend && npm install && npm run build\n"
)


def build_authoring_app(
    host: str = "127.0.0.1",
    source: str | None = None,
    page: Path | None = None,
) -> Starlette:
    """Build the editor's application, refusing to be reachable.

    Parameters
    ----------
    source
        The configuration document to edit. Defaults to the one this
        installation is configured with.
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

    if source is None:
        from app.config.app import configuration as cfg

        source = cfg.PYGEOAPI_CONFIG

    token = secrets.token_urlsafe(32)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def session(request: Request) -> JSONResponse:
        """Take the token in a body, hand back a cookie.

        The one route the guard lets past, because it is how a browser
        gets in at all — and it does its own checking rather than being
        an exception to the rule.

        The answer says nothing about the token. Repeating it would only
        make another copy to leak, in a body a log or a devtools session
        would happily keep, and the caller has it already.
        """
        try:
            offered = (await request.json()).get("token", "")
        except Exception:
            offered = ""
        if not isinstance(offered, str) or not secrets.compare_digest(offered, token):
            return JSONResponse({"message": "Unauthenticated"}, status_code=401)

        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            EDITOR_TOKEN_COOKIE,
            token,
            httponly=True,  # no script needs to read it; one that could would be a way out
            samesite="strict",  # never sent along with a request another site started
            # Not `secure`: this is loopback over plain HTTP, and a
            # secure cookie would simply never be stored.
        )
        return response

    class TokenGuard(BaseHTTPMiddleware):
        """Every request carries the secret, not just the first one.

        Header or cookie: the same secret, two ways of holding it. A
        script sends the header; a page has been given the cookie, and
        cannot be made to send the header without first putting the token
        somewhere a page can read.
        """

        async def dispatch(self, request: Request, call_next):
            # The page itself is not guarded: it is where the token gets
            # typed in, so a guard there would leave no way to supply
            # one. What protects it is that this role is not reachable
            # from anywhere but this machine. What it can *do* still
            # needs the secret, which is everything under /editor.
            if not request.url.path.startswith("/editor/") or request.url.path == (
                "/editor/session"
            ):
                return await call_next(request)
            offered = request.headers.get(EDITOR_TOKEN_HEADER) or request.cookies.get(
                EDITOR_TOKEN_COOKIE, ""
            )
            if not secrets.compare_digest(offered, token):
                return JSONResponse({"message": "Unauthenticated"}, status_code=401)
            return await call_next(request)

    async def not_built(request: Request) -> PlainTextResponse:
        """Explain a missing build instead of answering 404.

        A 404 would read as a bug in the editor rather than a step
        nobody has run. The API works without the page, so this is not a
        reason to refuse to start — only something to say at the moment
        someone goes looking for it.
        """
        return PlainTextResponse(_NOT_BUILT, status_code=503)

    page = DEFAULT_PAGE if page is None else page
    # `html=True` serves index.html for directory paths, and looks for
    # 404.html when it finds nothing. It does **not** fall back for deep
    # links, so the page stays a single one (ADR-0008).
    serve_page = (
        Mount("/", app=StaticFiles(directory=page, html=True))
        if (page / "index.html").is_file()
        else Route("/", not_built, methods=["GET"])
    )

    app = Starlette(
        routes=[
            Route("/editor/health", health, methods=["GET"]),
            Route("/editor/session", session, methods=["POST"]),
            *build_routes(source),
            serve_page,  # last: a mount at "/" would shadow everything above
        ],
        middleware=[Middleware(TokenGuard)],
    )
    app.state.editor_token = token
    app.state.editor_source = source
    return app
