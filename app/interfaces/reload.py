"""pygeoapi config reload webhook (ADR-0003).

The control plane POSTs here after writing the config to the bucket:
202 right away, work in the background, idempotence via ETag. Security
does NOT live here: the ``/admin`` mount is wrapped with the very auth
chain of the configured mode (``main._wrap_pygeoapi_asgi``).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.config.logging import create_logger

if TYPE_CHECKING:
    from app.pygeoapi.holder import PygeoapiHolder

logger = create_logger("app.interfaces.reload")


class ReloadManager:
    """Coalesces concurrent reloads and records the last outcome.

    Possible ``last.outcome`` values: ``applied`` (new config in
    service), ``unchanged`` (same ETag, no rebuild), ``failed`` (new
    config invalid: the previous one keeps serving).
    """

    def __init__(self, holder: PygeoapiHolder, source: str):
        self._holder = holder
        self._source = source
        self._running = False
        self._last: dict | None = None

    def status(self) -> dict:
        """The last reload outcome plus whether one is currently running."""
        return {"status": "running" if self._running else "idle", "last": self._last}

    async def trigger(self) -> dict:
        """Start a background reload unless one is already running."""
        if self._running:
            return {"status": "already-running"}
        self._running = True
        asyncio.get_running_loop().create_task(self._run())
        return {"status": "started"}

    def _record(self, outcome: str, **extra) -> None:
        self._last = {
            "outcome": outcome,
            "at": datetime.now(UTC).isoformat(),
            **extra,
        }

    async def _run(self) -> None:
        from app.config.source import aload_config_source, astat_config_source

        try:
            meta = await astat_config_source(self._source)
            if meta.etag is not None and meta.etag == self._holder.etag:
                self._record("unchanged", etag=meta.etag)
                return
            document = await aload_config_source(self._source)
            subapp = await asyncio.to_thread(self._build, document.config)
            self._holder.swap(subapp, etag=document.etag)
            self._record("applied", etag=document.etag)
            logger.info(f"pygeoapi config reloaded from {self._source} (etag={document.etag})")
        except Exception as e:  # the old one keeps serving: rollback for free
            self._record("failed", error=f"{type(e).__name__}: {e}")
            logger.error(f"config reload failed, still serving the previous config: {e}")
        finally:
            self._running = False

    @staticmethod
    def _build(config: dict):
        from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

        return build_pygeoapi_subapp(config, build_openapi(config))


def build_admin_app(manager: ReloadManager) -> Starlette:
    """The admin sub-app, to be mounted wrapped in the auth chain."""

    async def reload_endpoint(request: Request) -> JSONResponse:
        if request.method == "POST":
            return JSONResponse(await manager.trigger(), status_code=202)
        return JSONResponse(manager.status())

    return Starlette(routes=[Route("/config/reload", reload_endpoint, methods=["GET", "POST"])])
