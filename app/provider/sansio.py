"""Sans-I/O cores and the two drivers that feed them (ADR-0010, decision 6).

A core is a generator: it *yields* ``(offset, length)`` requests,
*receives* the bytes, and *returns* its result. It knows nothing about
where the bytes come from, so it is tested once, in memory, and gives a
provider both faces for free::

    def get_tiles(...):
        return drive_sync(self._tile(z, x, y), self.ranges)

    async def aget_tiles(...):
        return await drive(self._tile(z, x, y), self.ranges)
"""

from __future__ import annotations

import asyncio  # re-exported so tests can pin "no thread is opened here"
from collections.abc import Generator

from app.provider.storage.ranges import ByteRanges

type Request = tuple[int, int]
"""One ranged read: ``(offset, length)``."""

type Core[T] = Generator[Request, bytes, T]
"""A parser step machine: yields requests, receives bytes, returns ``T``."""

__all__ = ["Core", "Request", "asyncio", "drive", "drive_sync"]


def drive_sync[T](core: Core[T], ranges: ByteRanges) -> T:
    """Run ``core`` to completion with synchronous reads."""
    try:
        offset, length = next(core)
        while True:
            offset, length = core.send(ranges.read(offset, length))
    except StopIteration as done:
        return done.value


async def drive[T](core: Core[T], ranges: ByteRanges) -> T:
    """Run ``core`` to completion with awaited reads; no thread involved."""
    try:
        offset, length = next(core)
        while True:
            offset, length = core.send(await ranges.aread(offset, length))
    except StopIteration as done:
        return done.value
