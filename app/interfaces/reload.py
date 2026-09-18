"""pygeoapi config reload webhook (ADR-0003).

The control plane POSTs here after writing the config to the bucket:
202 right away, work in the background, idempotence via ETag. Security
does NOT live here: the ``/admin`` mount is wrapped with the very auth
chain of the configured mode (``main._wrap_pygeoapi_asgi``).
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
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

#: Names this process in the status endpoint, so a control plane sampling
#: it through a load balancer can tell one worker from another and read
#: whether every worker it has seen serves the same revision. Drawn at
#: import, hence once per process. Deliberately not the PID: this is
#: opaque, not enumerable, and says nothing about the host — the status
#: endpoint sits behind the auth chain, but there is no reason to hand
#: out operating-system identifiers even there.
INSTANCE = secrets.token_hex(4)


class ReloadManager:
    """Coalesces concurrent reloads and records the last outcome.

    Possible ``last.outcome`` values: ``applied`` (new config in
    service), ``unchanged`` (same ETag, no rebuild), ``failed`` (new
    config invalid: the previous one keeps serving).
    """

    def __init__(
        self,
        holder: PygeoapiHolder,
        source: str,
        artifact_target: str | None = None,
        on_reload: Callable[[dict], None] | None = None,
    ):
        self._holder = holder
        self._source = source
        self._artifact_target = artifact_target
        # Announced after a successful swap, with the new OpenAPI
        # document. The MCP tool list is generated from it and has to
        # follow — but this module has no business knowing that, so it
        # only says what changed and lets the caller decide.
        self._on_reload = on_reload
        self._running = False
        self._last: dict | None = None

    def status(self) -> dict:
        """What this process serves, and what its last reload did.

        ``etag`` is the revision **in service** — the holder's, not the
        last attempt's. The two differ exactly when it matters: a worker
        whose last reload failed still serves the previous revision, and a
        control plane waiting for every worker to converge has to read
        that as "not yet", not as progress.
        """
        return {
            "status": "running" if self._running else "idle",
            "instance": INSTANCE,
            "etag": self._holder.etag,
            "last": self._last,
        }

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
            subapp, openapi = await asyncio.to_thread(self._build, document.config)
            self._holder.swap(subapp, etag=document.etag)
            self._record("applied", etag=document.etag)
            logger.info(f"pygeoapi config reloaded from {self._source} (etag={document.etag})")
            if self._on_reload is not None:
                # Deliberately not fatal: the configuration is already
                # serving, and a listener that fails should not turn a
                # good reload into a reported failure.
                try:
                    self._on_reload(openapi)
                except Exception as e:
                    logger.warning(f"a reload listener failed: {type(e).__name__}: {e}")
            await self._write_artifact(openapi)
        except Exception as e:  # the old one keeps serving: rollback for free
            self._record("failed", error=f"{type(e).__name__}: {e}")
            logger.error(f"config reload failed, still serving the previous config: {e}")
        finally:
            self._running = False

    async def _write_artifact(self, openapi: dict) -> None:
        """Refresh the derived artifact after an applied reload.

        The artifact must follow config changes or it lies to the
        control plane. Never fatal: the reload itself already succeeded.
        """
        if self._artifact_target is None:
            return
        try:
            import yaml

            from app.provider.storage import (
                StorageBridge,
                load_store,
                split_source,
            )

            base, key = split_source(self._artifact_target)
            await StorageBridge(load_store(base)).awrite(
                key, yaml.safe_dump(openapi, sort_keys=False).encode("utf-8")
            )
            logger.info(f"OpenAPI artifact refreshed at {self._artifact_target}")
        except Exception as e:
            logger.warning(
                f"Could not refresh the OpenAPI artifact at {self._artifact_target}: {e}"
            )

    @staticmethod
    def _build(config: dict):
        from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

        openapi = build_openapi(config)
        return build_pygeoapi_subapp(config, openapi), openapi


class ConfigPoller:
    """Ask for a reload at a fixed interval, so every worker converges.

    The reload is per process: with several uvicorn workers the webhook
    reaches one and the others keep serving the previous revision
    (issue #455). There is no shared memory to fix that with, and none
    wanted — the source of truth is the configuration source, and each
    process converges to it by asking ``ReloadManager.trigger()`` on a
    timer. Everything that makes that cheap and safe already exists in
    the manager: the ETag comparison that turns a poll into a ``HEAD``
    and nothing else when nothing changed, the atomic swap, the rollback
    on a bad document, the coalescing of concurrent runs.

    The loop never dies. A source that blinks is a log line and another
    attempt one interval later, not a worker frozen on an old revision.
    Cancellation is the only way out, and it is honoured promptly.
    """

    def __init__(self, trigger: Callable[[], Awaitable[dict]], interval: float) -> None:
        self._trigger = trigger
        self._interval = interval

    async def run(self) -> None:
        """Poll until cancelled; a failed attempt is logged and retried."""
        while True:
            try:
                await self._trigger()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"configuration poll failed, will retry: {type(e).__name__}: {e}")
            await asyncio.sleep(self._interval)


def build_admin_app(manager: ReloadManager) -> Starlette:
    """The admin sub-app, to be mounted wrapped in the auth chain."""

    async def reload_endpoint(request: Request) -> JSONResponse:
        if request.method == "POST":
            return JSONResponse(await manager.trigger(), status_code=202)
        return JSONResponse(manager.status())

    return Starlette(routes=[Route("/config/reload", reload_endpoint, methods=["GET", "POST"])])
