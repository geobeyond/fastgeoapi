"""Byte ranges of one object: the seam between a format's parser and the storage layer.

A format read by ranges (PMTiles, COG, FlatGeobuf) only needs "these
bytes at this offset". :class:`ByteRanges` is that contract, with a
sync and an async side; :class:`ObjectRanges` binds it to one key of an
:class:`ObjectStore`, so the parser never learns about buckets.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.provider.storage.base import ObjectStore


@runtime_checkable
class ByteRanges(Protocol):
    """Ranged reads over one object, sync and async."""

    def read(self, offset: int, length: int) -> bytes:
        """``length`` bytes from ``offset``."""
        ...

    async def aread(self, offset: int, length: int) -> bytes:
        """Async twin of :meth:`read`."""
        ...

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Several ``(offset, length)`` ranges, in request order."""
        ...

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Async twin of :meth:`read_many`."""
        ...


class ObjectRanges:
    """:class:`ByteRanges` over ``key`` in ``store``."""

    def __init__(self, store: ObjectStore, key: str) -> None:
        self._store = store
        self._key = key

    def read(self, offset: int, length: int) -> bytes:
        """``length`` bytes from ``offset``."""
        return self._store.get_range(self._key, offset, length)

    async def aread(self, offset: int, length: int) -> bytes:
        """Async twin of :meth:`read`."""
        return await self._store.aget_range(self._key, offset, length)

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Several ranges, in request order."""
        return self._store.get_ranges(self._key, ranges)

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Async twin of :meth:`read_many`."""
        return await self._store.aget_ranges(self._key, ranges)
