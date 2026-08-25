"""Storage layer contracts (ADR-0003): structural Protocol.

Any object with the four operations is a valid backend — the Protocol
is the type that circulates in the config loader, providers and tests.
"""

import dataclasses
from datetime import UTC, datetime

import pytest

from app.provider.storage.base import ObjectMeta, ObjectStore


class _FakeStore:
    """In-memory backend: satisfies the Protocol by structure, not inheritance."""

    def __init__(self, objects: dict[str, bytes]):
        self._objects = objects

    def get(self, path: str) -> bytes:
        return self._objects[path]

    async def aget(self, path: str) -> bytes:
        return self._objects[path]

    def head(self, path: str) -> ObjectMeta:
        data = self._objects[path]
        return ObjectMeta(
            path=path,
            size=len(data),
            etag=str(hash(data)),
            last_modified=datetime.now(UTC),
        )

    async def ahead(self, path: str) -> ObjectMeta:
        return self.head(path)

    def put(self, path: str, data: bytes) -> None:
        self._objects[path] = data

    async def aput(self, path: str, data: bytes) -> None:
        self._objects[path] = data

    def keys(self, prefix: str = "") -> list[str]:
        return [key for key in self._objects if key.startswith(prefix)]


def test_structural_conformance_is_runtime_checkable():
    store = _FakeStore({"cfg.yml": b"server: {}"})
    assert isinstance(store, ObjectStore)


def test_non_conforming_object_is_rejected():
    assert not isinstance(object(), ObjectStore)


def test_meta_is_immutable():
    meta = ObjectMeta(path="x", size=1, etag=None, last_modified=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.etag = "nuovo"  # ty: ignore[invalid-assignment]


class _ReaderOnly:
    """Reads only, no write and no listing: NOT a valid backend anymore."""

    def get(self, path: str) -> bytes:
        return b""

    async def aget(self, path: str) -> bytes:
        return b""

    def head(self, path: str) -> ObjectMeta:
        return ObjectMeta(path=path, size=0, etag=None, last_modified=None)

    async def ahead(self, path: str) -> ObjectMeta:
        return self.head(path)


def test_protocol_requires_write_primitives():
    """ADR-0005 follow-up: the openapi artifact needs ``put``/``aput``."""
    assert not isinstance(_ReaderOnly(), ObjectStore)
