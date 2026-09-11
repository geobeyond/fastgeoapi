"""A format parser that never does I/O, driven by two tiny drivers (ADR-0010, decision 6)."""

import pytest

import app.provider.sansio as sansio
from app.provider.sansio import Core, drive, drive_sync


class _Memory:
    """ByteRanges over an in-memory blob, recording every request."""

    def __init__(self, blob: bytes):
        self.blob = blob
        self.reads: list[tuple[int, int]] = []

    def read(self, offset, length):
        self.reads.append((offset, length))
        return self.blob[offset : offset + length]

    async def aread(self, offset, length):
        return self.read(offset, length)

    def read_many(self, ranges):
        return [self.read(offset, length) for offset, length in ranges]

    async def aread_many(self, ranges):
        return self.read_many(ranges)


def length_prefixed_payload() -> Core[bytes]:
    """Read a 4-byte big-endian length, then that many bytes after it."""
    header = yield (0, 4)
    size = int.from_bytes(header, "big")
    payload = yield (4, size)
    # `yield` requests plus `return result` IS the sans-I/O core shape.
    return payload  # ruff: ignore[return-in-generator]


BLOB = (5).to_bytes(4, "big") + b"hello" + b"tail"


def test_drive_sync_feeds_the_core_until_it_returns():
    memory = _Memory(BLOB)
    assert drive_sync(length_prefixed_payload(), memory) == b"hello"
    assert memory.reads == [(0, 4), (4, 5)]


@pytest.mark.asyncio
async def test_drive_gives_the_same_answer_without_a_thread(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("the async driver must not open a thread")

    monkeypatch.setattr(sansio.asyncio, "to_thread", forbidden)
    memory = _Memory(BLOB)
    assert await drive(length_prefixed_payload(), memory) == b"hello"
    assert memory.reads == [(0, 4), (4, 5)]


def test_a_core_that_returns_before_asking_is_driven_too():
    def nothing() -> Core[int]:
        return 42  # ruff: ignore[return-in-generator]
        yield  # makes this a generator function

    assert drive_sync(nothing(), _Memory(BLOB)) == 42


@pytest.mark.asyncio
async def test_the_async_driver_handles_the_same_early_return():
    def nothing() -> Core[int]:
        return 42  # ruff: ignore[return-in-generator]
        yield

    assert await drive(nothing(), _Memory(BLOB)) == 42
