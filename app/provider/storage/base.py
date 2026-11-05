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
        """Read the whole object synchronously.

        Parameters
        ----------
        path
            The key of the object in the store.

        Returns
        -------
        bytes
            The content of the object.
        """
        ...

    async def aget(self, path: str) -> bytes:
        """Read the whole object asynchronously.

        Parameters
        ----------
        path
            The key of the object in the store.

        Returns
        -------
        bytes
            The content of the object.
        """
        ...

    def head(self, path: str) -> ObjectMeta:
        """Read the metadata of the object synchronously, without its content.

        Parameters
        ----------
        path
            The key of the object in the store.

        Returns
        -------
        ObjectMeta
            Its size, ETag and date.
        """
        ...

    async def ahead(self, path: str) -> ObjectMeta:
        """Read the metadata of the object asynchronously, without its content.

        Parameters
        ----------
        path
            The key of the object in the store.

        Returns
        -------
        ObjectMeta
            Its size, ETag and date.
        """
        ...

    def put(self, path: str, data: bytes) -> None:
        """Write the whole object synchronously, replacing any object at ``path``.

        Parameters
        ----------
        path
            The key of the object in the store.
        data
            The content to write.
        """
        ...

    async def aput(self, path: str, data: bytes) -> None:
        """Write the whole object asynchronously, replacing any object at ``path``.

        Parameters
        ----------
        path
            The key of the object in the store.
        data
            The content to write.
        """
        ...

    def keys(self, prefix: str = "") -> list[str]:
        """List the keys of the objects under a prefix, recursively.

        Named ``keys`` rather than ``list``: a method called ``list``
        shadows the builtin inside the class body, so every ``list[...]``
        annotation after it stops resolving.

        Parameters
        ----------
        prefix
            The key prefix; empty lists the whole store.

        Returns
        -------
        list[str]
            One key per object.
        """
        ...

    def entries(self, prefix: str = "") -> list[ObjectMeta]:
        """List the objects under a prefix, recursively, each with its size and date.

        A listing that fails raises an ``OSError``, whatever the backend.

        Parameters
        ----------
        prefix
            The key prefix; empty lists the whole store.

        Returns
        -------
        list[ObjectMeta]
            One entry per object.
        """
        ...

    async def aentries(self, prefix: str = "") -> list[ObjectMeta]:
        """List the objects under a prefix, asynchronously, as :meth:`entries` does.

        Parameters
        ----------
        prefix
            The key prefix; empty lists the whole store.

        Returns
        -------
        list[ObjectMeta]
            One entry per object.
        """
        ...

    def delete(self, path: str) -> None:
        """Remove the object synchronously; a missing object is not an error.

        Parameters
        ----------
        path
            The key of the object in the store.
        """
        ...

    async def adelete(self, path: str) -> None:
        """Remove the object asynchronously; a missing object is not an error.

        Parameters
        ----------
        path
            The key of the object in the store.
        """
        ...

    def get_range(
        self, path: str, offset: int, length: int, *, if_match: str | None = None
    ) -> bytes:
        """Read ``length`` bytes starting at ``offset``, synchronously.

        With ``if_match`` the read happens only while the object's ETag is
        that value; otherwise it raises :class:`ObjectChangedError`.

        Parameters
        ----------
        path
            The key of the object in the store.
        offset
            The first byte to read.
        length
            How many bytes to read.
        if_match
            The ETag the object must still have, or None to read any version.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        ...

    async def aget_range(
        self, path: str, offset: int, length: int, *, if_match: str | None = None
    ) -> bytes:
        """Read ``length`` bytes starting at ``offset``, asynchronously.

        With ``if_match`` the read happens only while the object's ETag is
        that value; otherwise it raises :class:`ObjectChangedError`.

        Parameters
        ----------
        path
            The key of the object in the store.
        offset
            The first byte to read.
        length
            How many bytes to read.
        if_match
            The ETag the object must still have, or None to read any version.

        Returns
        -------
        bytes
            The bytes of the range.
        """
        ...

    def get_ranges(self, path: str, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges synchronously, in request order.

        Backends may coalesce neighbouring ranges into fewer requests;
        the result is one ``bytes`` per requested range regardless.

        Parameters
        ----------
        path
            The key of the object in the store.
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        ...

    async def aget_ranges(self, path: str, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges asynchronously, in request order.

        Backends may coalesce neighbouring ranges into fewer requests;
        the result is one ``bytes`` per requested range regardless.

        Parameters
        ----------
        path
            The key of the object in the store.
        ranges
            The ``(offset, length)`` pairs to read.

        Returns
        -------
        list[bytes]
            The bytes of each range, in the order of ``ranges``.
        """
        ...
