"""obstore → ObjectStore Protocol adapter.

obstore returns a ``GetResult`` from ``get`` and a dict from ``head``:
this module reduces both to the contract shapes (bytes,
``ObjectMeta``). When the object is missing obstore natively raises
``FileNotFoundError``: it passes through unchanged. A listing that fails
raises an ``OSError``, so no caller of the storage layer handles an obstore
exception.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
from datetime import timedelta
from typing import Any

import obstore
from obstore.exceptions import BaseError, PreconditionError

from app.provider.storage.base import ObjectChangedError, ObjectMeta


class ObstoreStore:
    """Protocol backend over any obstore store."""

    def __init__(self, store: Any):
        """Wrap ``store``.

        Parameters
        ----------
        store
            An obstore store: local, in memory, HTTP or a bucket.
        """
        self._store = store

    @property
    def backend(self) -> Any:
        """The obstore store itself, for libraries that speak obstore natively.

        async-tiff and its siblings take the store object and do their
        own ranged reads through it; handing it over keeps the provider
        free of any obstore import while the storage layer stays the one
        place that knows how the store was built.

        Returns
        -------
        Any
            The wrapped obstore store.
        """
        return self._store

    def sign(self, path: str, expires_in: timedelta) -> str:
        """Sign a GET URL for ``path``, valid for ``expires_in``.

        Only the cloud stores sign: obstore raises ``ValueError`` for a
        local or in-memory store.

        Parameters
        ----------
        path
            The key of the object in the store.
        expires_in
            How long the URL stays valid.

        Returns
        -------
        str
            The presigned URL.
        """
        return obstore.sign(self._store, "GET", path, expires_in)

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
        return bytes(self._store.get(path).bytes())

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
        result = await self._store.get_async(path)
        return bytes(await result.bytes_async())

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
        return self._meta(self._store.head(path))

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
        return self._meta(await self._store.head_async(path))

    def put(self, path: str, data: bytes) -> None:
        """Write the whole object synchronously, replacing any object at ``path``.

        Parameters
        ----------
        path
            The key of the object in the store.
        data
            The content to write.
        """
        self._store.put(path, data)

    async def aput(self, path: str, data: bytes) -> None:
        """Write the whole object asynchronously, replacing any object at ``path``.

        Parameters
        ----------
        path
            The key of the object in the store.
        data
            The content to write.
        """
        await self._store.put_async(path, data)

    def keys(self, prefix: str = "") -> list[str]:
        """List the keys of the objects under a prefix, recursively.

        Parameters
        ----------
        prefix
            The key prefix; empty lists the whole store.

        Returns
        -------
        list[str]
            One key per object.
        """
        return [entry["path"] for batch in self._store.list(prefix) for entry in batch]

    def entries(self, prefix: str = "") -> list[ObjectMeta]:
        """List the objects under a prefix, recursively, with their metadata.

        Parameters
        ----------
        prefix
            The key prefix; empty lists the whole store.

        Returns
        -------
        list[ObjectMeta]
            One entry per object.

        Raises
        ------
        OSError
            If obstore cannot list the store.
        """
        try:
            return [
                self._meta(entry) for batch in obstore.list(self._store, prefix) for entry in batch
            ]
        except BaseError as error:
            raise OSError(str(error)) from error

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

        Raises
        ------
        OSError
            If obstore cannot list the store.
        """
        try:
            return [
                self._meta(entry)
                async for batch in obstore.list(self._store, prefix)
                for entry in batch
            ]
        except BaseError as error:
            raise OSError(str(error)) from error

    def delete(self, path: str) -> None:
        """Remove the object synchronously; a missing object is not an error.

        A local store raises for a missing object and a bucket does not, so
        the error is dropped here.

        Parameters
        ----------
        path
            The key of the object in the store.
        """
        with suppress(FileNotFoundError):
            obstore.delete(self._store, path)

    async def adelete(self, path: str) -> None:
        """Remove the object asynchronously; a missing object is not an error.

        A local store raises for a missing object and a bucket does not, so
        the error is dropped here.

        Parameters
        ----------
        path
            The key of the object in the store.
        """
        with suppress(FileNotFoundError):
            await obstore.delete_async(self._store, path)

    def get_range(
        self, path: str, offset: int, length: int, *, if_match: str | None = None
    ) -> bytes:
        """Read ``length`` bytes starting at ``offset`` in one request, synchronously.

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

        Raises
        ------
        ObjectChangedError
            If ``if_match`` is given and the object has another ETag.
        """
        if if_match is None:
            return bytes(self._store.get_range(path, start=offset, length=length))
        try:
            result = obstore.get(
                self._store,
                path,
                options={"if_match": if_match, "range": (offset, offset + length)},
            )
        except PreconditionError:
            raise ObjectChangedError(path) from None
        return bytes(result.bytes())

    async def aget_range(
        self, path: str, offset: int, length: int, *, if_match: str | None = None
    ) -> bytes:
        """Read ``length`` bytes starting at ``offset`` in one request, asynchronously.

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

        Raises
        ------
        ObjectChangedError
            If ``if_match`` is given and the object has another ETag.
        """
        if if_match is None:
            return bytes(await self._store.get_range_async(path, start=offset, length=length))
        try:
            result = await obstore.get_async(
                self._store,
                path,
                options={"if_match": if_match, "range": (offset, offset + length)},
            )
        except PreconditionError:
            raise ObjectChangedError(path) from None
        return bytes(await result.bytes_async())

    def get_ranges(self, path: str, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges synchronously, in request order.

        obstore coalesces neighbouring ranges less than 1 MiB apart into one request.

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
        if not ranges:
            return []
        starts = [offset for offset, _ in ranges]
        lengths = [length for _, length in ranges]
        return [
            bytes(chunk) for chunk in self._store.get_ranges(path, starts=starts, lengths=lengths)
        ]

    async def aget_ranges(self, path: str, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Read several ``(offset, length)`` ranges asynchronously, in request order.

        obstore coalesces neighbouring ranges less than 1 MiB apart into one request.

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
        if not ranges:
            return []
        starts = [offset for offset, _ in ranges]
        lengths = [length for _, length in ranges]
        chunks = await self._store.get_ranges_async(path, starts=starts, lengths=lengths)
        return [bytes(chunk) for chunk in chunks]

    @staticmethod
    def _meta(raw: dict) -> ObjectMeta:
        """Turn the metadata dict obstore returns into an :class:`ObjectMeta`.

        Parameters
        ----------
        raw
            The dict of a listing or of ``head``.

        Returns
        -------
        ObjectMeta
            The same metadata, with obstore's ``e_tag`` as ``etag``.
        """
        return ObjectMeta(
            path=raw["path"],
            size=raw["size"],
            etag=raw.get("e_tag"),
            last_modified=raw.get("last_modified"),
        )
