"""Byte ranges of one object: the seam between a format's parser and the storage layer.

A format read by ranges (PMTiles, COG, FlatGeobuf) only needs "these
bytes at this offset". :class:`ByteRanges` is that contract, with a
sync and an async side; :class:`ObjectRanges` binds it to one key of an
:class:`ObjectStore`, so the parser never learns about buckets.
"""

from __future__ import annotations

import asyncio
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


class SingleFlightRanges:
    """A :class:`ByteRanges` wrapper: identical awaited reads in flight share one fetch.

    Fifty tile requests arriving together on a cold provider each want
    the same header, root and leaf directories; without this they read
    them fifty times (measured on Overture: 245 ranged reads for 50
    tiles instead of 58). This is de-duplication of what is in flight,
    not a cache: a later identical read fetches again. Flights are kept
    per event loop; the synchronous side passes straight through.
    """

    def __init__(self, inner: ByteRanges) -> None:
        self.inner = inner
        self._flights: dict[int, dict[tuple[int, int], asyncio.Future[bytes]]] = {}

    def read(self, offset: int, length: int) -> bytes:
        """Sync read, untouched."""
        return self.inner.read(offset, length)

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Sync ranged reads, untouched."""
        return self.inner.read_many(ranges)

    async def aread(self, offset: int, length: int) -> bytes:
        """Await the fetch already in flight for this range, or start it."""
        loop = asyncio.get_running_loop()
        flights = self._flights.setdefault(id(loop), {})
        key = (offset, length)
        flight = flights.get(key)
        if flight is None:
            flight = loop.create_task(self.inner.aread(offset, length))
            flights[key] = flight
            flight.add_done_callback(lambda _done: flights.pop(key, None))
        return await flight

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Async ranged reads, untouched: batches are unique by construction."""
        return await self.inner.aread_many(ranges)
