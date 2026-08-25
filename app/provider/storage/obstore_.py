"""obstore → ObjectStore Protocol adapter.

obstore returns a ``GetResult`` from ``get`` and a dict from ``head``:
this module reduces both to the contract shapes (bytes,
``ObjectMeta``). When the object is missing obstore natively raises
``FileNotFoundError``: it passes through unchanged.
"""

from __future__ import annotations

from typing import Any

from app.provider.storage.base import ObjectMeta


class ObstoreStore:
    """Protocol backend over any obstore store."""

    def __init__(self, store: Any):
        self._store = store

    def get(self, path: str) -> bytes:
        """Read the whole object as bytes."""
        return bytes(self._store.get(path).bytes())

    async def aget(self, path: str) -> bytes:
        """Read the whole object as bytes, asynchronously."""
        result = await self._store.get_async(path)
        return bytes(await result.bytes_async())

    def head(self, path: str) -> ObjectMeta:
        """Object metadata as :class:`ObjectMeta`."""
        return self._meta(self._store.head(path))

    async def ahead(self, path: str) -> ObjectMeta:
        """Object metadata as :class:`ObjectMeta`, asynchronously."""
        return self._meta(await self._store.head_async(path))

    def put(self, path: str, data: bytes) -> None:
        """Write the whole object."""
        self._store.put(path, data)

    async def aput(self, path: str, data: bytes) -> None:
        """Write the whole object, asynchronously."""
        await self._store.put_async(path, data)

    def keys(self, prefix: str = "") -> list[str]:
        """Object keys under a prefix, recursively."""
        return [entry["path"] for batch in self._store.list(prefix) for entry in batch]

    @staticmethod
    def _meta(raw: dict) -> ObjectMeta:
        return ObjectMeta(
            path=raw["path"],
            size=raw["size"],
            etag=raw.get("e_tag"),
            last_modified=raw.get("last_modified"),
        )
