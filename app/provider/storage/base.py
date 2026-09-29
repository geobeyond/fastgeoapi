"""Storage layer contracts.

Contracts live in ``base.py`` as in ``pygeoapi/provider/base.py``.
No module outside this package imports the external dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
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


class ObjectChangedError(Exception):
    """The object no longer has the ETag that a conditional read asked for."""


@runtime_checkable
class ObjectStore(Protocol):
    """A valid backend knows how to do these things, each in a sync and an async form.

    The interface is agnostic of the underlying storage implementation:
    conformance is structural, not by inheritance. Whole-object reads
    and writes serve the configuration; ranged reads serve the formats
    that are read piecewise (ADR-0010).
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

    def entries(self, prefix: str = "") -> list[ObjectMeta]:
        """The objects under a prefix, recursively, each with its size and date."""
        ...

    async def aentries(self, prefix: str = "") -> list[ObjectMeta]:
        """Async twin of :meth:`entries`."""
        ...

    def delete(self, path: str) -> None:
        """Remove the object; a missing object is not an error."""
        ...

    async def adelete(self, path: str) -> None:
        """Async twin of :meth:`delete`."""
        ...

    def get_range(
        self, path: str, offset: int, length: int, *, if_match: str | None = None
    ) -> bytes:
        """Read ``length`` bytes starting at ``offset``, synchronously.

        With ``if_match`` the read happens only while the object's ETag is
        that value; otherwise it raises :class:`ObjectChangedError`.
        """
        ...

    async def aget_range(
        self, path: str, offset: int, length: int, *, if_match: str | None = None
    ) -> bytes:
        """Async twin of :meth:`get_range`."""
        ...

    def get_ranges(self, path: str, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges, in request order.

        Backends may coalesce neighbouring ranges into fewer requests;
        the result is one ``bytes`` per requested range regardless.
        """
        ...

    async def aget_ranges(self, path: str, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Async twin of :meth:`get_ranges`."""
        ...
