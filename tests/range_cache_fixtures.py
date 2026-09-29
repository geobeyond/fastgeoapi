"""Stores for the range cache tests: in memory, counting their reads, or broken like a full disk."""

from __future__ import annotations

from typing import Any

from obstore.store import MemoryStore


def memory_store() -> Any:
    """A fresh in-memory store behind the storage layer's adapter."""
    from app.provider.storage import ObstoreStore

    return ObstoreStore(MemoryStore())


class Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class CountingStore:
    """An object store that records the ranged reads, HEADs and writes reaching it."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.range_reads: list[tuple[int, int]] = []
        self.heads = 0
        self.writes: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def head(self, path: str) -> Any:
        self.heads += 1
        return self.inner.head(path)

    async def ahead(self, path: str) -> Any:
        self.heads += 1
        return await self.inner.ahead(path)

    def get_range(
        self, path: str, offset: int, length: int, *, if_match: str | None = None
    ) -> bytes:
        self.range_reads.append((offset, length))
        return self.inner.get_range(path, offset, length, if_match=if_match)

    async def aget_range(
        self, path: str, offset: int, length: int, *, if_match: str | None = None
    ) -> bytes:
        self.range_reads.append((offset, length))
        return await self.inner.aget_range(path, offset, length, if_match=if_match)

    def put(self, path: str, data: bytes) -> None:
        self.writes.append(path)
        self.inner.put(path, data)

    async def aput(self, path: str, data: bytes) -> None:
        self.writes.append(path)
        await self.inner.aput(path, data)


class BrokenStore:
    """A cache store whose every operation fails, as a full or read-only disk does."""

    error = PermissionError("the cache directory is read-only")

    def _fail(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error

    async def _afail(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error

    get = put = delete = entries = _fail
    aget = aput = adelete = aentries = _afail


def range_cache(
    store: Any, *, max_bytes: int = 1 << 20, revalidate_seconds: float = 300.0, clock: Any = None
) -> Any:
    """A range cache over ``store``, with a clock the test can move."""
    from app.provider.storage import RangeCache

    return RangeCache(
        lambda: store,
        max_bytes=max_bytes,
        revalidate_seconds=revalidate_seconds,
        clock=clock or Clock(),
    )
