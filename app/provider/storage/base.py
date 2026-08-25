"""Storage layer contracts.

Contracts live in ``base.py`` as in ``pygeoapi/provider/base.py``.
No module outside this package imports the external dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ObjectMeta:
    """Minimal object metadata; the ETag drives reload idempotence."""

    path: str
    size: int
    etag: str | None
    last_modified: datetime | None


@runtime_checkable
class ObjectStore(Protocol):
    """A valid backend knows how to do these four things.

    the interface is agnostic of the underlying storage implementation:
    conformance is structural, not by inheritance.
    """

    def get(self, path: str) -> bytes:
        """Read the whole object synchronously."""
        ...

    async def aget(self, path: str) -> bytes:
        """Read the whole object asynchronously."""
        ...

    def head(self, path: str) -> ObjectMeta:
        """Object metadata, synchronously."""
        ...

    async def ahead(self, path: str) -> ObjectMeta:
        """Object metadata, asynchronously."""
        ...

    def put(self, path: str, data: bytes) -> None:
        """Write the whole object synchronously."""
        ...

    async def aput(self, path: str, data: bytes) -> None:
        """Write the whole object asynchronously."""
        ...

    def keys(self, prefix: str = "") -> list[str]:
        """Object keys under a prefix, recursively.

        Named ``keys`` rather than ``list``: a method called ``list``
        shadows the builtin inside the class body, so every ``list[...]``
        annotation after it stops resolving.
        """
        ...
