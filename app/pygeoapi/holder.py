"""ASGI indirection for the atomic swap of the pygeoapi sub-app (ADR-0003)."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class PygeoapiHolder:
    """Delegates every request to the current app; a reload replaces it.

    In-flight requests hold a reference to the old app and finish on
    it: the swap never touches them. It is the target of both the
    ``FASTGEOAPI_CONTEXT`` mount and the MCP ``ASGITransport``, so both
    faces always see the same config.
    """

    def __init__(self) -> None:
        self.current: ASGIApp | None = None
        self.etag: str | None = None

    def swap(self, app: ASGIApp, etag: str | None = None) -> None:
        self.current = app
        self.etag = etag

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        app = self.current
        if app is None:
            response = JSONResponse(
                {"status": "not-ready", "reason": "pygeoapi not built yet"},
                status_code=503,
            )
            await response(scope, receive, send)
            return
        await app(scope, receive, send)
