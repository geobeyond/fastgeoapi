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
import re
import threading
import time
from collections.abc import Callable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

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

OFF = "off"
"""The setting that turns the range cache off."""

_ENTRY = re.compile(r"[0-9a-f]{32}/[0-9a-f]{32}/\d+-\d+")
"""The shape of a key :meth:`RangeCache.key` builds from the digests of a source and a version."""


def digest(text: str) -> str:
    """Fingerprint ``text`` in 32 hex characters, safe in a path, for the parts of a cache key.

    Parameters
    ----------
    text
        What the key part stands for: a source or an ETag.

    Returns
    -------
    str
        The first 32 hex characters of its SHA-256.
    """
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def version_of(meta: ObjectMeta) -> str:
    """Name the version of the object ``meta`` describes, as it appears in keys and URLs.

    Parameters
    ----------
    meta
        The metadata of the object.

    Returns
    -------
    str
        The digest of its ETag, or ``unversioned`` without one.
    """
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
        """Prepare a cache whose store ``opener`` builds at the first use, off the event loop.

        Parameters
        ----------
        opener
            Builds the store that holds the entries.
        max_bytes
            The cap on the size of the entries.
        revalidate_seconds
            How many seconds a version read with a HEAD is trusted.
        clock
            The clock of the warnings and of the revalidation, in seconds.
        """
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
        self._sweep_threads: set[threading.Thread] = set()
        self._warned: dict[str, float] = {}

    @classmethod
    def at(cls, location: str, *, max_bytes: int, revalidate_seconds: float = 300.0) -> RangeCache:
        """Build a cache in a local directory only this user reads, or in a store named by URL.

        Nothing is created before the first read or write. A local directory
        is then created with mode 0700, or brought back to 0700 when it
        already exists: the entries are bytes of the objects, private
        buckets included.

        Parameters
        ----------
        location
            A local path, or the URL of a store.
        max_bytes
            The cap on the size of the entries. Past it, a sweep deletes the
            entries written first, down to nine tenths of the cap.
        revalidate_seconds
            How many seconds a version read with a HEAD is trusted.

        Returns
        -------
        RangeCache
            The cache, before any I/O.
        """

        def open_store() -> ObjectStore:
            """Open the store of the entries, creating a local directory first."""
            if "://" not in location:
                # Entries are bytes of the objects, private buckets included.
                # makedirs leaves a directory that already exists as it is.
                os.makedirs(location, mode=0o700, exist_ok=True)
                os.chmod(location, 0o700)
            return load_store(location)

        return cls(open_store, max_bytes=max_bytes, revalidate_seconds=revalidate_seconds)

    @staticmethod
    def build_key(source: str, version: str, offset: int, length: int) -> str:
        """Build the key a range lives at.

        Parameters
        ----------
        source
            The digest of the object.
        version
            The digest of its version, from :func:`version_of`.
        offset
            The first byte of the range.
        length
            How many bytes the range has.

        Returns
        -------
        str
            ``source/version/offset-length``.
        """
        return f"{source}/{version}/{offset}-{length}"

    def get(self, key: str, length: int) -> bytes | None:
        """Read the entry at ``key`` synchronously.

        Parameters
        ----------
        key
            The entry's key, from :meth:`build_key`.
        length
            The length the entry must have.

        Returns
        -------
        bytes | None
            The entry, or None when it is missing, has another length or
            the store fails. An entry of another length is deleted.
        """
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
        """Read the entry at ``key`` asynchronously.

        Parameters
        ----------
        key
            The entry's key, from :meth:`build_key`.
        length
            The length the entry must have.

        Returns
        -------
        bytes | None
            The entry, or None when it is missing, has another length or
            the store fails. An entry of another length is deleted.
        """
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
        """Keep ``data`` at ``key``, unless it is larger than a tenth of the cap.

        A write that fails is logged, and the entry is not kept. The sweep
        the write may start runs on a thread of its own, so the reader that
        wrote the entry does not wait for the listing and the deletes.

        Parameters
        ----------
        key
            The entry's key, from :meth:`build_key`.
        data
            The bytes of the range.
        """
        if len(data) > self._tenth:
            return
        try:
            self._open().put(key, data)
        except Exception as error:
            self._warn("write", error)
            return
        if self._is_sweep_due(len(data)):
            thread = threading.Thread(
                target=self._sweep_in_background, name="range-cache-sweep", daemon=True
            )
            with self._lock:
                self._sweep_threads.add(thread)
            thread.start()

    def _sweep_in_background(self) -> None:
        """Sweep on the current thread, then forget the thread."""
        try:
            self.sweep()
        finally:
            with self._lock:
                self._sweep_threads.discard(threading.current_thread())

    async def aput(self, key: str, data: bytes) -> None:
        """Keep ``data`` at ``key`` asynchronously, unless it is larger than a tenth of the cap.

        A write that fails is logged, and the entry is not kept. The sweep
        the write may start runs as a task on the loop.

        Parameters
        ----------
        key
            The entry's key, from :meth:`build_key`.
        data
            The bytes of the range.
        """
        if len(data) > self._tenth:
            return
        try:
            await (await self._aopen()).aput(key, data)
        except Exception as error:
            self._warn("write", error)
            return
        if self._is_sweep_due(len(data)):
            task = asyncio.get_running_loop().create_task(self.asweep())
            self._sweeps.add(task)
            task.add_done_callback(self._sweeps.discard)

    def sweep(self) -> None:
        """Delete the entries written first, synchronously, until the cache is under its target.

        Only the cache's own entries count and are deleted. A failure is
        logged and ends the sweep.
        """
        try:
            store = self._open()
            for path in self._find_surplus(store.list_entries()):
                store.delete(path)
        except Exception as error:
            self._warn("sweep", error)
        finally:
            with self._lock:
                self._sweeping = False

    async def asweep(self) -> None:
        """Delete the entries written first, asynchronously, until the cache is under its target.

        Only the cache's own entries count and are deleted. A failure is
        logged and ends the sweep.
        """
        try:
            store = await self._aopen()
            for path in self._find_surplus(await store.alist_entries()):
                await store.adelete(path)
        except Exception as error:
            self._warn("sweep", error)
        finally:
            with self._lock:
                self._sweeping = False

    async def drain(self) -> None:
        """Wait for the sweeps running in the background, on the loop and on threads.

        A sweep that fails has already logged its error, so none is raised here.
        """
        if self._sweeps:
            await asyncio.gather(*self._sweeps, return_exceptions=True)
        with self._lock:
            threads = list(self._sweep_threads)
        for thread in threads:
            await asyncio.to_thread(thread.join)

    def _find_surplus(self, entries: list[ObjectMeta]) -> list[str]:
        """Pick the entries to delete, oldest first, to bring the cache under its target.

        Parameters
        ----------
        entries
            The listing of the store that holds the cache.

        Returns
        -------
        list[str]
            The keys to delete; empty while the cache is under its cap.
        """
        # The location may hold other objects: only the cache's own entries count and are deleted.
        entries = [entry for entry in entries if _ENTRY.fullmatch(entry.path)]
        total = sum(entry.size for entry in entries)
        if total <= self.max_bytes:
            return []
        target = self.max_bytes * SWEEP_TARGET
        surplus = []
        for entry in sorted(entries, key=_get_written_at):
            if total <= target:
                break
            surplus.append(entry.path)
            total -= entry.size
        return surplus

    def _is_sweep_due(self, written: int) -> bool:
        """Count ``written`` bytes and tell whether a sweep should start now.

        A sweep is due once a tenth of the cap has been written since the
        last one and none is running; the caller then runs it.

        Parameters
        ----------
        written
            The bytes of the entry just written.

        Returns
        -------
        bool
            True when the caller should start a sweep.
        """
        with self._lock:
            self._written += written
            if self._sweeping or self._written < self._tenth:
                return False
            self._written, self._sweeping = 0, True
            return True

    def _open(self) -> ObjectStore:
        """Open the store of the entries at the first call, synchronously.

        Returns
        -------
        ObjectStore
            The store, the same one at every call.
        """
        with self._lock:
            if self._store is None:
                self._store = self._opener()
            return self._store

    async def _aopen(self) -> ObjectStore:
        """Open the store of the entries at the first call, on a thread.

        Returns
        -------
        ObjectStore
            The store, the same one at every call.
        """
        store = self._store
        if store is None:
            # The opener may create a directory: that happens in a thread.
            store = await asyncio.to_thread(self._open)
        return store

    def _discard(self, key: str) -> None:
        """Delete the entry at ``key`` synchronously; a failure is only logged.

        Parameters
        ----------
        key
            The entry's key.
        """
        try:
            self._open().delete(key)
        except Exception as error:
            self._warn("delete", error)

    async def _adiscard(self, key: str) -> None:
        """Delete the entry at ``key`` asynchronously; a failure is only logged.

        Parameters
        ----------
        key
            The entry's key.
        """
        try:
            await (await self._aopen()).adelete(key)
        except Exception as error:
            self._warn("delete", error)

    def _warn(self, kind: str, error: Exception, then: str = "the source is read instead") -> None:
        """Log a failure of the store, at most once a minute for each kind.

        Parameters
        ----------
        kind
            What failed: read, write, sweep, delete or revalidation.
        error
            The error; only its type is logged, since its message may name
            the object.
        then
            What happens instead, for the log line.
        """
        now = self.clock()
        with self._lock:
            last = self._warned.get(kind)
            if last is not None and now - last < WARNING_INTERVAL:
                return
            self._warned[kind] = now
        # The type only: the message of a store error may name the object.
        logger.warning(f"range cache {kind} failed with {type(error).__name__}; {then}")


class CachedRanges:
    """Byte ranges of one object, by version, through a :class:`RangeCache`.

    The version is the object's ETag. A HEAD reads it, and it is trusted
    for the cache's ``revalidate_seconds``, or until a read finds the
    object changed. Reads go through :meth:`at`, pinned to one version,
    so a reader that parsed the object at one version never receives
    bytes of another.
    """

    def __init__(self, store: ObjectStore, key: str, cache: RangeCache, *, source: str) -> None:
        """Prepare the ranges of the object at ``key`` in ``store``.

        Parameters
        ----------
        store
            The store that holds the object.
        key
            The key of the object in ``store``.
        cache
            The cache the ranges are kept in.
        source
            What names the object in cache keys, by its digest: a
            provider's ``data``, say.
        """
        self.store = store
        self.key = key
        self.cache = cache
        self.source = digest(source)
        self._meta: ObjectMeta | None = None
        self._checked = 0.0
        self._versions: dict[str, ObjectMeta] = {}
        self._pinned: dict[str, ByteRanges] = {}
        self._lock = threading.Lock()
        self._revalidating: asyncio.Task | None = None

    def meta(self) -> ObjectMeta:
        """Read the object's metadata synchronously, again with a HEAD past ``revalidate_seconds``.

        When that HEAD fails, the version read last answers and a warning is
        logged; the next call past the TTL tries again. When it fails before
        any version was read, the store's error reaches the caller.

        Returns
        -------
        ObjectMeta
            The size, the ETag and the modification time of the object.
        """
        meta = self._get_fresh_meta()
        if meta is not None:
            return meta
        try:
            return self._remember(self.store.head(self.key))
        except Exception as error:
            return self._fall_back_to_known(error)

    async def ameta(self) -> ObjectMeta:
        """Read the object's metadata asynchronously, again with a HEAD past ``revalidate_seconds``.

        When that HEAD fails, the version read last answers and a warning is
        logged. When it fails before any version was read, the store's
        error reaches the caller.

        Returns
        -------
        ObjectMeta
            The size, the ETag and the modification time of the object.
        """
        meta = self._get_fresh_meta()
        if meta is not None:
            return meta
        try:
            return self._remember(await self.store.ahead(self.key))
        except Exception as error:
            return self._fall_back_to_known(error)

    def _fall_back_to_known(self, error: Exception) -> ObjectMeta:
        """Answer a failed HEAD with the version read last, or raise ``error`` without one.

        Parameters
        ----------
        error
            The error of the HEAD, raised again when no version was read yet.

        Returns
        -------
        ObjectMeta
            The version read last.
        """
        known = self.known_meta()
        if known is None:
            raise error
        self.cache._warn("revalidation", error, then="the known version stays")
        return known

    async def ameta_without_waiting(self) -> ObjectMeta:
        """Pick the version to read now: the known one, while a HEAD past the TTL runs behind.

        Only a reader with no version known yet waits for the store. On a
        slow route a HEAD costs seconds, and a reader that cannot wait for
        it gets the version it read last; a change shows up once the HEAD
        behind it returns, or as soon as a pinned read finds the object
        changed.

        Returns
        -------
        ObjectMeta
            The version to read.
        """
        meta = self._get_fresh_meta()
        if meta is not None:
            return meta
        known = self.known_meta()
        if known is None:
            return await self.ameta()
        with self._lock:
            if self._revalidating is None or self._revalidating.done():
                self._revalidating = asyncio.get_running_loop().create_task(self._arevalidate())
        return known

    def known_meta(self) -> ObjectMeta | None:
        """Return the version read last, however old.

        Returns
        -------
        ObjectMeta | None
            The version, or None before the first HEAD.
        """
        with self._lock:
            return self._meta

    async def _arevalidate(self) -> None:
        """Read the version again with a HEAD; a failure is only logged."""
        try:
            self._remember(await self.store.ahead(self.key))
        except Exception as error:
            # The next reader past the TTL tries again.
            self.cache._warn("revalidation", error, then="the known version stays")

    def invalidate(self) -> None:
        """Forget the version: the next :meth:`meta` asks the store again."""
        with self._lock:
            self._meta = None

    def find_known(self, version: str) -> ObjectMeta | None:
        """Find the metadata of one of the last versions seen.

        Parameters
        ----------
        version
            The version, as :func:`version_of` names it.

        Returns
        -------
        ObjectMeta | None
            Its metadata, or None when it is not among the last versions seen.
        """
        with self._lock:
            return self._versions.get(version)

    def at(self, meta: ObjectMeta) -> ByteRanges:
        """Give the ranged reads pinned to the version ``meta`` names.

        Identical reads in flight share one fetch. An object without an
        ETag has no version to pin, so its reads go to the store and are
        never kept.

        Parameters
        ----------
        meta
            The metadata of the version to read.

        Returns
        -------
        ByteRanges
            The reads of that version, the same object for the same version.
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

    def _get_fresh_meta(self) -> ObjectMeta | None:
        """Return the version read last while it is still trusted.

        Returns
        -------
        ObjectMeta | None
            The version, or None when none was read or ``revalidate_seconds`` have passed.
        """
        with self._lock:
            if self._meta is None:
                return None
            if self.cache.clock() - self._checked >= self.cache.revalidate_seconds:
                return None
            return self._meta

    def _remember(self, meta: ObjectMeta) -> ObjectMeta:
        """Keep ``meta`` as the current version, among the last versions seen.

        Parameters
        ----------
        meta
            The metadata a HEAD returned.

        Returns
        -------
        ObjectMeta
            ``meta`` itself.
        """
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
        """Pin the reads to the version ``meta`` names.

        Parameters
        ----------
        cached
            The ranges of the object, which hold its store and the cache.
        meta
            The metadata of the version, with its ETag.

        Raises
        ------
        ValueError
            If ``meta`` has no ETag.
        """
        if meta.etag is None:
            raise ValueError("a pinned read needs the object's ETag")
        self._cached = cached
        self._etag = meta.etag
        self._version = digest(meta.etag)

    def read(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset`` synchronously, from the cache or the object.

        Parameters
        ----------
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range; a range past the end comes back short
            and is not kept.

        Raises
        ------
        ObjectChangedError
            If the object no longer has this version.
        """
        key = RangeCache.build_key(self._cached.source, self._version, offset, length)
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
        """Read ``length`` bytes from ``offset`` asynchronously, from the cache or the object.

        Parameters
        ----------
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range; a range past the end comes back short
            and is not kept.

        Raises
        ------
        ObjectChangedError
            If the object no longer has this version.
        """
        key = RangeCache.build_key(self._cached.source, self._version, offset, length)
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
        """Read several ranges synchronously, each through the cache, in request order.

        Parameters
        ----------
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        return [self.read(offset, length) for offset, length in ranges]

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ranges concurrently, each through the cache, in request order.

        Parameters
        ----------
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        return list(await asyncio.gather(*(self.aread(offset, n) for offset, n in ranges)))


def _get_written_at(entry: ObjectMeta) -> tuple[float, str]:
    """Sort key of an entry: when it was written, then its key.

    Parameters
    ----------
    entry
        An entry of the listing.

    Returns
    -------
    tuple[float, str]
        The timestamp, 0 without a date, and the key.
    """
    written = entry.last_modified.timestamp() if entry.last_modified else 0.0
    return written, entry.path


def get_cache_base_dir(cfg: Any) -> Path:
    """Find the cache root in the settings.

    Parameters
    ----------
    cfg
        fastgeoapi's settings.

    Returns
    -------
    Path
        ``FASTGEOAPI_CACHE_DIR``, or ``.cache`` in the working directory.
    """
    root = getattr(cfg, "FASTGEOAPI_CACHE_DIR", None)
    return Path(root) if root else Path.cwd() / ".cache"


def _is_turned_off(location: str | None) -> bool:
    """Tell whether ``FASTGEOAPI_RANGE_CACHE`` turns the cache off.

    Parameters
    ----------
    location
        The value of the setting, or None when it is not set.

    Returns
    -------
    bool
        True for ``off``, in any case and with any spaces around it.
    """
    return location is not None and location.strip().lower() == OFF


def build_range_cache(cfg: Any) -> RangeCache | None:
    """Build the range cache fastgeoapi's settings describe.

    Parameters
    ----------
    cfg
        fastgeoapi's settings.

    Returns
    -------
    RangeCache | None
        The cache, or None when the settings turn it off.
    """
    location = getattr(cfg, "FASTGEOAPI_RANGE_CACHE", None)
    if _is_turned_off(location):
        return None
    return RangeCache.at(
        location or str(get_cache_base_dir(cfg) / "ranges"),
        max_bytes=int(cfg.FASTGEOAPI_RANGE_CACHE_MAX_MB) * 1024 * 1024,
        revalidate_seconds=float(cfg.FASTGEOAPI_RANGE_CACHE_REVALIDATE_SECONDS),
    )


def _get_settings() -> Any | None:
    """Load fastgeoapi's settings, when this process has them.

    Returns
    -------
    Any | None
        The settings, or None when fastgeoapi is not configured.
    """
    # Imported here: building the settings needs a configured fastgeoapi,
    # and providers are also built by tools that only have pygeoapi.
    try:
        from app.config.app import configuration
    except (ImportError, ValueError):
        return None
    return configuration


def get_default_cache_base_dir() -> Path | None:
    """Find the cache root fastgeoapi's settings name.

    Returns
    -------
    Path | None
        The root, or None without settings.
    """
    settings = _get_settings()
    return None if settings is None else get_cache_base_dir(settings)


@lru_cache(maxsize=1)
def default_range_cache() -> RangeCache | None:
    """Build the range cache of this process once, from fastgeoapi's settings.

    Returns
    -------
    RangeCache | None
        The cache, or None without settings or when they turn it off.
    """
    settings = _get_settings()
    return None if settings is None else build_range_cache(settings)


def range_cache_enabled() -> bool:
    """Tell whether remote data is read through the range cache, as far as the settings tell.

    Without settings the answer is the default, on: a definition checked
    by a tool is judged as the server will run it.

    Returns
    -------
    bool
        False only when the settings turn the cache off.
    """
    settings = _get_settings()
    return settings is None or not _is_turned_off(getattr(settings, "FASTGEOAPI_RANGE_CACHE", None))
