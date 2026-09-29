"""Byte ranges of registered objects, served over HTTP on the loopback interface.

A reader outside the process, such as the map renderer, reads an object
through this server instead of from its bucket: the reads go through the
range cache, and signed URLs never leave the process. The server listens
on 127.0.0.1 only, on a port the system picks, and a random token in
every path keeps other local processes from guessing URLs. Parsing a
request is pure; the connection handling around it uses h11.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import threading
import weakref
from contextlib import suppress
from dataclasses import dataclass

import h11

from app.config.logging import create_logger
from app.provider.storage.base import ObjectChangedError, ObjectMeta
from app.provider.storage.cache import CachedRanges, version_of

logger = create_logger("app.provider.storage.loopback")

_RANGE = re.compile(r"bytes=(\d+)-(\d+)")


@dataclass(frozen=True)
class RangeRequest:
    """A request the server can answer: bytes ``start`` to ``end``, both included."""

    source: str
    version: str
    start: int
    end: int


@dataclass(frozen=True)
class Refusal:
    """The status that refuses a request."""

    status: int


def parse_request(
    method: str, target: str, range_header: str | None, *, token: str
) -> RangeRequest | Refusal:
    """What a request asks for, or the status that refuses it.

    Only ``GET /<token>/<source>/<version>`` with a single ``bytes=a-b``
    range is answered. A wrong token gets the same 404 as an unknown
    object, so the answer does not tell which part was wrong.
    """
    if method != "GET":
        return Refusal(405)
    parts = target.split("?", 1)[0].split("/")
    if len(parts) != 4 or parts[0] or not secrets.compare_digest(parts[1].encode(), token.encode()):
        return Refusal(404)
    match = _RANGE.fullmatch(range_header or "")
    if match is None or int(match[2]) < int(match[1]):
        return Refusal(416)
    return RangeRequest(parts[2], parts[3], int(match[1]), int(match[2]))


def clamp(request: RangeRequest, size: int) -> tuple[int, int] | None:
    """Offset and length of the request inside an object of ``size`` bytes; None past its end."""
    if request.start >= size:
        return None
    return request.start, min(request.end, size - 1) - request.start + 1


def partial_headers(offset: int, length: int, size: int) -> list[tuple[str, str]]:
    """The headers of a 206 response carrying ``length`` bytes from ``offset``."""
    return [
        ("content-type", "application/octet-stream"),
        ("content-length", str(length)),
        ("content-range", f"bytes {offset}-{offset + length - 1}/{size}"),
        ("accept-ranges", "bytes"),
    ]


class RangeSources:
    """The objects the server may serve, by the digest of their source."""

    def __init__(self) -> None:
        self._sources: dict[str, CachedRanges] = {}
        self._lock = threading.Lock()

    def register(self, cached: CachedRanges) -> None:
        """Serve ``cached``; the last registration of a source wins."""
        with self._lock:
            self._sources[cached.source] = cached

    def unregister(self, cached: CachedRanges) -> None:
        """Stop serving ``cached``, unless a later registration replaced it."""
        with self._lock:
            if self._sources.get(cached.source) is cached:
                del self._sources[cached.source]

    def get(self, source: str) -> CachedRanges | None:
        """The object registered for ``source``."""
        with self._lock:
            return self._sources.get(source)


SOURCES = RangeSources()
"""The registrations of this process."""


def _empty(status: int, *headers: tuple[str, str]) -> tuple[int, list[tuple[str, str]], bytes]:
    return status, [("content-length", "0"), *headers], b""


class RangeServer:
    """Serves ranges of the objects in ``sources`` to readers on this machine."""

    def __init__(self, sources: RangeSources) -> None:
        """Nothing listens until :meth:`start`."""
        self._sources = sources
        self.token = secrets.token_urlsafe(32)
        self.port: int | None = None
        self.connections = 0
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._starting = asyncio.Lock()

    @property
    def sockets(self) -> tuple:
        """The listening sockets, once started."""
        return tuple(self._server.sockets) if self._server is not None else ()

    async def start(self) -> None:
        """Listen on 127.0.0.1, on a port the system picks; a second call does nothing."""
        async with self._starting:
            if self._server is None:
                self._server = await asyncio.start_server(self._serve, host="127.0.0.1", port=0)
                self.port = self._server.sockets[0].getsockname()[1]

    def url_for(self, cached: CachedRanges, meta: ObjectMeta) -> str:
        """The URL of ``cached`` at the version ``meta`` names, token included."""
        return f"http://127.0.0.1:{self.port}/{self.token}/{cached.source}/{version_of(meta)}"

    async def aclose(self) -> None:
        """Stop listening and close the connections still open."""
        server, self._server = self._server, None
        if server is None:
            return
        server.close()
        # Readers keep their connections alive, and wait_closed waits for them.
        for writer in list(self._clients):
            writer.close()
        await server.wait_closed()

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.connections += 1
        self._clients.add(writer)
        connection = h11.Connection(h11.SERVER)
        try:
            while True:
                request = await _next_request(connection, reader)
                if request is None:
                    return
                status, headers, body = await self._answer(request)
                writer.write(connection.send(h11.Response(status_code=status, headers=headers)))
                if body:
                    writer.write(connection.send(h11.Data(data=body)))
                writer.write(connection.send(h11.EndOfMessage()))
                await writer.drain()
                if connection.our_state is h11.MUST_CLOSE:
                    return
                connection.start_next_cycle()
        except (h11.ProtocolError, ConnectionError):
            return
        finally:
            self._clients.discard(writer)
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()

    async def _answer(self, request: h11.Request) -> tuple[int, list[tuple[str, str]], bytes]:
        range_header = next(
            (value.decode("latin-1") for name, value in request.headers if name == b"range"), None
        )
        asked = parse_request(
            request.method.decode("ascii"),
            request.target.decode("latin-1"),
            range_header,
            token=self.token,
        )
        if isinstance(asked, Refusal):
            return _empty(asked.status)
        cached = self._sources.get(asked.source)
        meta = cached.known(asked.version) if cached is not None else None
        if cached is None or meta is None:
            return _empty(404)
        window = clamp(asked, meta.size)
        if window is None:
            return _empty(416, ("content-range", f"bytes */{meta.size}"))
        offset, length = window
        try:
            data = await cached.at(meta).aread(offset, length)
        except ObjectChangedError:
            # The object changed under a version a reader still holds.
            return _empty(404)
        except Exception as error:
            logger.warning(f"loopback range read failed with {type(error).__name__}")
            return _empty(502)
        return 206, partial_headers(offset, len(data), meta.size), data


async def _next_request(
    connection: h11.Connection, reader: asyncio.StreamReader
) -> h11.Request | None:
    """The next request on the connection once it is complete; None when the peer has gone."""
    request = None
    while True:
        event = connection.next_event()
        if event is h11.NEED_DATA:
            connection.receive_data(await reader.read(65536))
        elif isinstance(event, h11.Request):
            request = event
        elif isinstance(event, h11.EndOfMessage):
            return request
        elif isinstance(event, h11.ConnectionClosed) or event is h11.PAUSED:
            return None


_SERVERS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, RangeServer] = (
    weakref.WeakKeyDictionary()
)


async def ensure_range_server() -> RangeServer:
    """The server of the running event loop, started at its first use."""
    loop = asyncio.get_running_loop()
    server = _SERVERS.get(loop)
    if server is None:
        server = _SERVERS[loop] = RangeServer(SOURCES)
    await server.start()
    return server


async def close_range_server() -> None:
    """Close the server of the running event loop, when it has one."""
    server = _SERVERS.pop(asyncio.get_running_loop(), None)
    if server is not None:
        await server.aclose()
