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
        """Read ``length`` bytes from ``offset`` synchronously.

        Parameters
        ----------
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        ...

    async def aread(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset`` asynchronously.

        Parameters
        ----------
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        ...

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges synchronously, in request order.

        Parameters
        ----------
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        ...

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges asynchronously, in request order.

        Parameters
        ----------
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        ...


class ObjectRanges:
    """:class:`ByteRanges` over ``key`` in ``store``."""

    def __init__(self, store: ObjectStore, key: str) -> None:
        """Bind the reads to ``key`` in ``store``.

        Parameters
        ----------
        store
            The store that holds the object.
        key
            The key of the object in ``store``.
        """
        self._store = store
        self._key = key

    def read(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset`` of the object, synchronously.

        Parameters
        ----------
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        return self._store.get_range(self._key, offset, length)

    async def aread(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset`` of the object, asynchronously.

        Parameters
        ----------
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        return await self._store.aget_range(self._key, offset, length)

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ranges of the object synchronously, in request order.

        Parameters
        ----------
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        return self._store.get_ranges(self._key, ranges)

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ranges of the object asynchronously, in request order.

        Parameters
        ----------
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
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
        """Wrap ``inner``.

        Parameters
        ----------
        inner
            The reads the flights are shared over.
        """
        self.inner = inner
        self._flights: dict[int, dict[tuple[int, int], asyncio.Future[bytes]]] = {}

    def read(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset`` synchronously, straight from ``inner``.

        Parameters
        ----------
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        return self.inner.read(offset, length)

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ranges synchronously, straight from ``inner``.

        Parameters
        ----------
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        return self.inner.read_many(ranges)

    async def aread(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes from ``offset``, awaiting the fetch already in flight for it.

        Without one in flight on this event loop, the read starts it, and
        the reads of the same range that arrive meanwhile await it too.

        Parameters
        ----------
        offset
            The first byte to read.
        length
            How many bytes to read.

        Returns
        -------
        bytes
            The bytes of the range.
        """
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
        """Read several ranges asynchronously, straight from ``inner``.

        A batch is unique by construction, so it is not shared.

        Parameters
        ----------
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        return await self.inner.aread_many(ranges)
