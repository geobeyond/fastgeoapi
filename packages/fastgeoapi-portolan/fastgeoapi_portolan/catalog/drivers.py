"""The drivers: they run a walk with a transport, one document at a time or several at once."""

from __future__ import annotations

import asyncio

from fastgeoapi_portolan.catalog.protocols import AsyncTransport, SchemaValidator, Transport
from fastgeoapi_portolan.catalog.results import Catalog, Collection, Items
from fastgeoapi_portolan.catalog.walk import Steps, T, walk, walk_items


def _run(steps: Steps[T], transport: Transport) -> T:
    def read(location: str) -> bytes | OSError:
        try:
            return transport.read(location)
        except OSError as error:
            return error

    try:
        locations = next(steps)
        while True:
            locations = steps.send({location: read(location) for location in locations})
    except StopIteration as done:
        return done.value


async def _run_async(steps: Steps[T], transport: AsyncTransport, concurrency: int) -> T:
    limit = asyncio.Semaphore(concurrency)

    async def read(location: str) -> bytes | OSError:
        async with limit:
            try:
                return await transport.read(location)
            except OSError as error:
                return error

    try:
        locations = next(steps)
        while True:
            replies = await asyncio.gather(*(read(location) for location in locations))
            locations = steps.send(dict(zip(locations, replies, strict=True)))
    except StopIteration as done:
        return done.value


def read_catalog(
    location: str,
    transport: Transport,
    *,
    only: frozenset[str] | None = None,
    validator: SchemaValidator | None = None,
) -> Catalog:
    """Walk the catalog at ``location``, reading one document at a time."""
    return _run(walk(location, only=only, validator=validator), transport)


async def read_catalog_async(
    location: str,
    transport: AsyncTransport,
    *,
    only: frozenset[str] | None = None,
    validator: SchemaValidator | None = None,
    concurrency: int = 16,
) -> Catalog:
    """Walk the catalog at ``location``, reading up to ``concurrency`` documents at once."""
    return await _run_async(walk(location, only=only, validator=validator), transport, concurrency)


def read_items(
    collection: Collection, transport: Transport, *, validator: SchemaValidator | None = None
) -> Items:
    """The items ``collection`` links, read one at a time."""
    return _run(walk_items(collection, validator=validator), transport)


async def read_items_async(
    collection: Collection,
    transport: AsyncTransport,
    *,
    validator: SchemaValidator | None = None,
    concurrency: int = 16,
) -> Items:
    """The items ``collection`` links, read up to ``concurrency`` at once."""
    return await _run_async(walk_items(collection, validator=validator), transport, concurrency)


class _InThread:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def read(self, location: str) -> bytes:
        return await asyncio.to_thread(self._transport.read, location)


def to_thread(transport: Transport) -> AsyncTransport:
    """``transport`` for the async driver: each read runs in a worker thread."""
    return _InThread(transport)
