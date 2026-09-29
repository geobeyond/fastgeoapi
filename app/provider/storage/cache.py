"""Byte ranges kept in an object store, shared by the processes of one machine.

An entry's key names the object, its version and the range, so an entry
never changes and a changed object gets keys of its own. The cap is kept
by deleting the entries written first, because an object store tells
when an entry was written but not when it was last read.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import threading
import time
from collections.abc import Callable

from app.config.logging import create_logger
from app.provider.storage.base import ObjectMeta, ObjectStore
from app.provider.storage.factory import load_store

logger = create_logger("app.provider.storage.cache")

SWEEP_TARGET = 0.9
"""After a sweep the cache holds at most this share of its cap."""

WARNING_INTERVAL = 60.0
"""Seconds between two warnings about the same kind of cache failure."""


def digest(text: str) -> str:
    """A short, path-safe fingerprint of ``text``, for the parts of a cache key."""
    return hashlib.sha256(text.encode()).hexdigest()[:32]


class RangeCache:
    """Byte ranges in an :class:`ObjectStore`, under a cap in bytes.

    Every operation has a sync and an async face, like the store. A
    failure of the store is logged, at most once a minute for each kind,
    and never reaches the reader: a failed read counts as a miss, and a
    failed write is dropped.
    """

    def __init__(
        self,
        opener: Callable[[], ObjectStore],
        *,
        max_bytes: int,
        revalidate_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """``opener`` builds the store at the first use, off the event loop."""
        self._opener = opener
        self._store: ObjectStore | None = None
        self.max_bytes = max_bytes
        self.revalidate_seconds = revalidate_seconds
        self.clock = clock
        self._lock = threading.Lock()
        # A tenth of the cap: the largest entry kept, and the bytes written
        # between two sweeps. The first write sweeps what earlier processes left.
        self._tenth = max(1, max_bytes // 10)
        self._written = self._tenth
        self._sweeping = False
        self._sweeps: set[asyncio.Task[None]] = set()
        self._warned: dict[str, float] = {}

    @classmethod
    def at(cls, location: str, *, max_bytes: int, revalidate_seconds: float = 300.0) -> RangeCache:
        """A cache in a local directory readable by this user only, or in a store named by URL."""

        def opener() -> ObjectStore:
            if "://" not in location:
                # Entries are bytes of the objects, private buckets included.
                os.makedirs(location, mode=0o700, exist_ok=True)
            return load_store(location)

        return cls(opener, max_bytes=max_bytes, revalidate_seconds=revalidate_seconds)

    @staticmethod
    def key(source: str, version: str, offset: int, length: int) -> str:
        """Where a range lives; ``source`` and ``version`` are digests."""
        return f"{source}/{version}/{offset}-{length}"

    def get(self, key: str, length: int) -> bytes | None:
        """The entry at ``key``; None when it is missing, has another length, or the store fails."""
        try:
            data = self._open().get(key)
        except FileNotFoundError:
            return None
        except Exception as error:
            self._warn("read", error)
            return None
        if len(data) != length:
            self._discard(key)
            return None
        return data

    async def aget(self, key: str, length: int) -> bytes | None:
        """Async twin of :meth:`get`."""
        try:
            data = await (await self._aopen()).aget(key)
        except FileNotFoundError:
            return None
        except Exception as error:
            self._warn("read", error)
            return None
        if len(data) != length:
            await self._adiscard(key)
            return None
        return data

    def put(self, key: str, data: bytes) -> None:
        """Keep ``data`` at ``key``, unless it is larger than a tenth of the cap."""
        if len(data) > self._tenth:
            return
        try:
            self._open().put(key, data)
        except Exception as error:
            self._warn("write", error)
            return
        if self._due(len(data)):
            self.sweep()

    async def aput(self, key: str, data: bytes) -> None:
        """Async twin of :meth:`put`; the sweep it may start runs in the background."""
        if len(data) > self._tenth:
            return
        try:
            await (await self._aopen()).aput(key, data)
        except Exception as error:
            self._warn("write", error)
            return
        if self._due(len(data)):
            task = asyncio.get_running_loop().create_task(self.asweep())
            self._sweeps.add(task)
            task.add_done_callback(self._sweeps.discard)

    def sweep(self) -> None:
        """Delete the entries written first until the cache is back under its target."""
        try:
            store = self._open()
            for path in self._surplus(store.entries()):
                store.delete(path)
        except Exception as error:
            self._warn("sweep", error)
        finally:
            with self._lock:
                self._sweeping = False

    async def asweep(self) -> None:
        """Async twin of :meth:`sweep`."""
        try:
            store = await self._aopen()
            for path in self._surplus(await store.aentries()):
                await store.adelete(path)
        except Exception as error:
            self._warn("sweep", error)
        finally:
            with self._lock:
                self._sweeping = False

    async def drain(self) -> None:
        """Wait for the sweeps running in the background."""
        if self._sweeps:
            await asyncio.gather(*self._sweeps, return_exceptions=True)

    def _surplus(self, entries: list[ObjectMeta]) -> list[str]:
        total = sum(entry.size for entry in entries)
        if total <= self.max_bytes:
            return []
        target = self.max_bytes * SWEEP_TARGET
        surplus = []
        for entry in sorted(entries, key=_written_at):
            if total <= target:
                break
            surplus.append(entry.path)
            total -= entry.size
        return surplus

    def _due(self, written: int) -> bool:
        with self._lock:
            self._written += written
            if self._sweeping or self._written < self._tenth:
                return False
            self._written, self._sweeping = 0, True
            return True

    def _open(self) -> ObjectStore:
        with self._lock:
            if self._store is None:
                self._store = self._opener()
            return self._store

    async def _aopen(self) -> ObjectStore:
        store = self._store
        if store is None:
            # The opener may create a directory: that happens in a thread.
            store = await asyncio.to_thread(self._open)
        return store

    def _discard(self, key: str) -> None:
        try:
            self._open().delete(key)
        except Exception as error:
            self._warn("delete", error)

    async def _adiscard(self, key: str) -> None:
        try:
            await (await self._aopen()).adelete(key)
        except Exception as error:
            self._warn("delete", error)

    def _warn(self, kind: str, error: Exception) -> None:
        now = self.clock()
        with self._lock:
            last = self._warned.get(kind)
            if last is not None and now - last < WARNING_INTERVAL:
                return
            self._warned[kind] = now
        # The type only: the message of a store error may name the object.
        logger.warning(
            f"range cache {kind} failed with {type(error).__name__}; the source is read instead"
        )


def _written_at(entry: ObjectMeta) -> tuple[float, str]:
    written = entry.last_modified.timestamp() if entry.last_modified else 0.0
    return written, entry.path
