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
from collections.abc import Callable, Sequence

from app.config.logging import create_logger
from app.provider.storage.base import ObjectChangedError, ObjectMeta, ObjectStore
from app.provider.storage.factory import load_store
from app.provider.storage.ranges import ByteRanges, ObjectRanges, SingleFlightRanges

logger = create_logger("app.provider.storage.cache")

SWEEP_TARGET = 0.9
"""After a sweep the cache holds at most this share of its cap."""

WARNING_INTERVAL = 60.0
"""Seconds between two warnings about the same kind of cache failure."""

MAX_VERSIONS = 2
"""Versions of one object remembered at once: the current one and the one before."""

UNVERSIONED = "unversioned"
"""The version of an object without an ETag: its reads always go to the object."""


def digest(text: str) -> str:
    """A short, path-safe fingerprint of ``text``, for the parts of a cache key."""
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def version_of(meta: ObjectMeta) -> str:
    """The version of the object ``meta`` describes, as it appears in keys and URLs."""
    return digest(meta.etag) if meta.etag else UNVERSIONED


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


class CachedRanges:
    """Byte ranges of one object, by version, through a :class:`RangeCache`.

    The version is the object's ETag. A HEAD reads it, and it is trusted
    for the cache's ``revalidate_seconds``, or until a read finds the
    object changed. Reads go through :meth:`at`, pinned to one version,
    so a reader that parsed the object at one version never receives
    bytes of another.
    """

    def __init__(self, store: ObjectStore, key: str, cache: RangeCache, *, source: str) -> None:
        """``source`` names the object in cache keys, by its digest: a provider's ``data``, say."""
        self.store = store
        self.key = key
        self.cache = cache
        self.source = digest(source)
        self._meta: ObjectMeta | None = None
        self._checked = 0.0
        self._versions: dict[str, ObjectMeta] = {}
        self._pinned: dict[str, ByteRanges] = {}
        self._lock = threading.Lock()

    def meta(self) -> ObjectMeta:
        """The object's metadata; a HEAD once ``revalidate_seconds`` have passed."""
        meta = self._fresh()
        return meta if meta is not None else self._remember(self.store.head(self.key))

    async def ameta(self) -> ObjectMeta:
        """Async twin of :meth:`meta`."""
        meta = self._fresh()
        return meta if meta is not None else self._remember(await self.store.ahead(self.key))

    def invalidate(self) -> None:
        """Forget the version: the next :meth:`meta` asks the store again."""
        with self._lock:
            self._meta = None

    def known(self, version: str) -> ObjectMeta | None:
        """The metadata of one of the last versions seen, by :func:`version_of`."""
        with self._lock:
            return self._versions.get(version)

    def at(self, meta: ObjectMeta) -> ByteRanges:
        """Ranged reads pinned to the version ``meta`` names.

        Identical reads in flight share one fetch. An object without an
        ETag has no version to pin, so its reads go to the store and are
        never kept.
        """
        version = version_of(meta)
        with self._lock:
            pinned = self._pinned.get(version)
            if pinned is None:
                inner: ByteRanges = (
                    ObjectRanges(self.store, self.key)
                    if meta.etag is None
                    else PinnedRanges(self, meta)
                )
                pinned = self._pinned[version] = SingleFlightRanges(inner)
                while len(self._pinned) > MAX_VERSIONS:
                    self._pinned.pop(next(iter(self._pinned)))
            return pinned

    def _fresh(self) -> ObjectMeta | None:
        with self._lock:
            if self._meta is None:
                return None
            if self.cache.clock() - self._checked >= self.cache.revalidate_seconds:
                return None
            return self._meta

    def _remember(self, meta: ObjectMeta) -> ObjectMeta:
        with self._lock:
            self._meta, self._checked = meta, self.cache.clock()
            version = version_of(meta)
            self._versions.pop(version, None)
            self._versions[version] = meta
            while len(self._versions) > MAX_VERSIONS:
                self._versions.pop(next(iter(self._versions)))
        return meta


class PinnedRanges:
    """:class:`ByteRanges` of one object at one version, kept in the cache."""

    def __init__(self, cached: CachedRanges, meta: ObjectMeta) -> None:
        """``meta`` must carry the ETag the reads are pinned to."""
        if meta.etag is None:
            raise ValueError("a pinned read needs the object's ETag")
        self._cached = cached
        self._etag = meta.etag
        self._version = digest(meta.etag)

    def read(self, offset: int, length: int) -> bytes:
        """``length`` bytes from ``offset``, from the cache or from the object at this version."""
        key = RangeCache.key(self._cached.source, self._version, offset, length)
        data = self._cached.cache.get(key, length)
        if data is None:
            try:
                data = self._cached.store.get_range(
                    self._cached.key, offset, length, if_match=self._etag
                )
            except ObjectChangedError:
                self._cached.invalidate()
                raise
            # A range that runs past the end comes back short: it is not kept.
            if len(data) == length:
                self._cached.cache.put(key, data)
        return data

    async def aread(self, offset: int, length: int) -> bytes:
        """Async twin of :meth:`read`."""
        key = RangeCache.key(self._cached.source, self._version, offset, length)
        data = await self._cached.cache.aget(key, length)
        if data is None:
            try:
                data = await self._cached.store.aget_range(
                    self._cached.key, offset, length, if_match=self._etag
                )
            except ObjectChangedError:
                self._cached.invalidate()
                raise
            if len(data) == length:
                await self._cached.cache.aput(key, data)
        return data

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Several ranges, each through the cache, in request order."""
        return [self.read(offset, length) for offset, length in ranges]

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Async twin of :meth:`read_many`."""
        return list(await asyncio.gather(*(self.aread(offset, n) for offset, n in ranges)))


def _written_at(entry: ObjectMeta) -> tuple[float, str]:
    written = entry.last_modified.timestamp() if entry.last_modified else 0.0
    return written, entry.path
