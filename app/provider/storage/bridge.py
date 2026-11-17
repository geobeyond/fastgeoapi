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
        """Wrap ``backend``.

        Parameters
        ----------
        backend
            A store with a sync side, an async side or both.
        """
        self._backend = backend

    def read(self, path: str) -> bytes:
        """Read the whole object synchronously, with ``asyncio.run`` on an async-only backend.

        Parameters
        ----------
        path
            The key of the object in the store.

        Returns
        -------
        bytes
            The content of the object.
        """
        if hasattr(self._backend, "get"):
            return self._backend.get(path)
        return asyncio.run(self._backend.aget(path))

    async def aread(self, path: str) -> bytes:
        """Read the whole object asynchronously, on a thread with a sync-only backend.

        Parameters
        ----------
        path
            The key of the object in the store.

        Returns
        -------
        bytes
            The content of the object.
        """
        if hasattr(self._backend, "aget"):
            return await self._backend.aget(path)
        return await asyncio.to_thread(self._backend.get, path)

    def stat(self, path: str) -> ObjectMeta:
        """Read the metadata of the object synchronously, bridged as :meth:`read` is.

        Parameters
        ----------
        path
            The key of the object in the store.

        Returns
        -------
        ObjectMeta
            Its size, ETag and date.
        """
        if hasattr(self._backend, "head"):
            return self._backend.head(path)
        return asyncio.run(self._backend.ahead(path))

    async def astat(self, path: str) -> ObjectMeta:
        """Read the metadata of the object asynchronously, bridged as :meth:`aread` is.

        Parameters
        ----------
        path
            The key of the object in the store.

        Returns
        -------
        ObjectMeta
            Its size, ETag and date.
        """
        if hasattr(self._backend, "ahead"):
            return await self._backend.ahead(path)
        return await asyncio.to_thread(self._backend.head, path)

    def write(self, path: str, data: bytes) -> None:
        """Write the whole object synchronously, bridged as :meth:`read` is.

        Parameters
        ----------
        path
            The key of the object in the store.
        data
            The content to write.
        """
        if hasattr(self._backend, "put"):
            return self._backend.put(path, data)
        return asyncio.run(self._backend.aput(path, data))

    async def awrite(self, path: str, data: bytes) -> None:
        """Write the whole object asynchronously, bridged as :meth:`aread` is.

        Parameters
        ----------
        path
            The key of the object in the store.
        data
            The content to write.
        """
        if hasattr(self._backend, "aput"):
            return await self._backend.aput(path, data)
        return await asyncio.to_thread(self._backend.put, path, data)

    def read_range(self, path: str, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset`` synchronously, bridged as :meth:`read` is.

        Parameters
        ----------
        path
            The key of the object in the store.
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        if hasattr(self._backend, "get_range"):
            return self._backend.get_range(path, offset, length)
        return asyncio.run(self._backend.aget_range(path, offset, length))

    async def aread_range(self, path: str, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset`` asynchronously, bridged as :meth:`aread` is.

        Parameters
        ----------
        path
            The key of the object in the store.
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        if hasattr(self._backend, "aget_range"):
            return await self._backend.aget_range(path, offset, length)
        return await asyncio.to_thread(self._backend.get_range, path, offset, length)
