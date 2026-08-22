"""Sync/async bridge over a possibly partial backend.

The sync side must NOT be called from inside a running event loop
(``asyncio.run`` would fail): startup and pygeoapi providers run
outside the loop or in the threadpool, which is exactly their use case.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.provider.storage.base import ObjectMeta


class StorageBridge:
    """Always exposes read/aread and stat/astat, filling the missing side."""

    def __init__(self, backend: Any):
        self._backend = backend

    def read(self, path: str) -> bytes:
        """Sync read; ``asyncio.run`` bridge when the backend is async-only."""
        if hasattr(self._backend, "get"):
            return self._backend.get(path)
        return asyncio.run(self._backend.aget(path))

    async def aread(self, path: str) -> bytes:
        """Async read; bridges via a thread when the backend is sync-only."""
        if hasattr(self._backend, "aget"):
            return await self._backend.aget(path)
        return await asyncio.to_thread(self._backend.get, path)

    def stat(self, path: str) -> ObjectMeta:
        """Sync metadata; bridges like :meth:`read`."""
        if hasattr(self._backend, "head"):
            return self._backend.head(path)
        return asyncio.run(self._backend.ahead(path))

    async def astat(self, path: str) -> ObjectMeta:
        """Async metadata; bridges like :meth:`aread`."""
        if hasattr(self._backend, "ahead"):
            return await self._backend.ahead(path)
        return await asyncio.to_thread(self._backend.head, path)
