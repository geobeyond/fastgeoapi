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
# The largest range served: the bytes are read into memory before they are
# sent, and a renderer reads headers, directories and tiles far smaller.
MAX_RANGE_BYTES = 64 << 20


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
    """Parse a request into what it asks for, or the status that refuses it.

    Only ``GET /<token>/<source>/<version>`` with a single ``bytes=a-b``
    range of at most :data:`MAX_RANGE_BYTES` is answered. A wrong token
    gets the same 404 as an unknown object, so the answer does not tell
    which part was wrong.

    Parameters
    ----------
    method
        The method of the request; only ``GET`` is served.
    target
        The target of the request, ``/<token>/<source>/<version>``.
    range_header
        The ``Range`` header, or None when the request has none.
    token
        The token of the server.

    Returns
    -------
    RangeRequest or Refusal
        What to read; or 405 for another method (RFC 9110, section 15.5.6),
        404 for a wrong path or token, and 416 for a range that is missing,
        malformed, multiple, reversed or larger than :data:`MAX_RANGE_BYTES`
        (RFC 9110, section 15.5.17).
    """
    if method != "GET":
        return Refusal(405)
    parts = target.split("?", 1)[0].split("/")
    if len(parts) != 4 or parts[0] or not secrets.compare_digest(parts[1].encode(), token.encode()):
        return Refusal(404)
    match = _RANGE.fullmatch(range_header or "")
    if match is None or int(match[2]) < int(match[1]):
        return Refusal(416)
    # RFC 9110, section 15.5.17: 416 also rejects a range the server will not serve.
    if int(match[2]) - int(match[1]) + 1 > MAX_RANGE_BYTES:
        return Refusal(416)
    return RangeRequest(parts[2], parts[3], int(match[1]), int(match[2]))


def clamp(request: RangeRequest, size: int) -> tuple[int, int] | None:
    """Fit the range of ``request`` inside an object of ``size`` bytes.

    Parameters
    ----------
    request
        The range asked for.
    size
        The size of the object.

    Returns
    -------
    tuple[int, int] | None
        The offset and the length to read, cut at the end of the object,
        or None when the range starts past it.
    """
    if request.start >= size:
        return None
    return request.start, min(request.end, size - 1) - request.start + 1


def build_partial_headers(offset: int, length: int, size: int) -> list[tuple[str, str]]:
    """Build the headers of a 206 response carrying ``length`` bytes from ``offset``.

    Parameters
    ----------
    offset
        The first byte of the body.
    length
        How many bytes the body has.
    size
        The size of the whole object, for ``Content-Range``.

    Returns
    -------
    list[tuple[str, str]]
        The header names and values.
    """
    return [
        ("content-type", "application/octet-stream"),
        ("content-length", str(length)),
        ("content-range", f"bytes {offset}-{offset + length - 1}/{size}"),
        ("accept-ranges", "bytes"),
    ]


class RangeSources:
    """The objects the server may serve, by the digest of their source."""

    def __init__(self) -> None:
        """Start with no object registered."""
        self._sources: dict[str, CachedRanges] = {}
        self._lock = threading.Lock()

    def register(self, cached: CachedRanges) -> None:
        """Serve ``cached``; the last registration of a source wins.

        Parameters
        ----------
        cached
            The ranges of the object, registered under the digest of its source.
        """
        with self._lock:
            self._sources[cached.source] = cached

    def unregister(self, cached: CachedRanges) -> None:
        """Stop serving ``cached``, unless a later registration replaced it.

        Parameters
        ----------
        cached
            The ranges registered with :meth:`register`.
        """
        with self._lock:
            if self._sources.get(cached.source) is cached:
                del self._sources[cached.source]

    def get(self, source: str) -> CachedRanges | None:
        """Find the object registered for ``source``.

        Parameters
        ----------
        source
            The digest of the source.

        Returns
        -------
        CachedRanges | None
            The registered ranges, or None when nothing is registered.
        """
        with self._lock:
            return self._sources.get(source)


SOURCES = RangeSources()
"""The registrations of this process."""


def _answer_empty(
    status: int, *headers: tuple[str, str]
) -> tuple[int, list[tuple[str, str]], bytes]:
    """Build a response with no body.

    Parameters
    ----------
    status
        The status code.
    *headers
        Headers to send besides ``Content-Length``.

    Returns
    -------
    tuple[int, list[tuple[str, str]], bytes]
        The status, the headers and an empty body.
    """
    return status, [("content-length", "0"), *headers], b""


class RangeServer:
    """Serves ranges of the objects in ``sources`` to readers on this machine."""

    def __init__(self, sources: RangeSources) -> None:
        """Prepare a server for ``sources``; nothing listens until :meth:`start`.

        Parameters
        ----------
        sources
            The objects the server may serve.
        """
        self._sources = sources
        self.token = secrets.token_urlsafe(32)
        self.port: int | None = None
        self.connections = 0
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._starting = asyncio.Lock()

    @property
    def sockets(self) -> tuple:
        """The listening sockets, once started.

        Returns
        -------
        tuple
            The sockets, empty before :meth:`start`.
        """
        return tuple(self._server.sockets) if self._server is not None else ()

    async def start(self) -> None:
        """Listen on 127.0.0.1, on a port the system picks; a second call does nothing."""
        async with self._starting:
            if self._server is None:
                self._server = await asyncio.start_server(self._serve, host="127.0.0.1", port=0)
                self.port = self._server.sockets[0].getsockname()[1]

    def url_for(self, cached: CachedRanges, meta: ObjectMeta) -> str:
        """Build the URL of ``cached`` at the version ``meta`` names, token included.

        Parameters
        ----------
        cached
            The registered ranges of the object.
        meta
            The metadata of the version to serve.

        Returns
        -------
        str
            ``http://127.0.0.1:<port>/<token>/<source>/<version>``.
        """
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
        """Answer the requests of one connection until the peer closes it.

        Parameters
        ----------
        reader
            The stream the requests arrive on.
        writer
            The stream the responses go out on.
        """
        self.connections += 1
        self._clients.add(writer)
        connection = h11.Connection(h11.SERVER)
        try:
            while True:
                request = await _read_next_request(connection, reader)
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
        """Answer one request with the range it asks for, or with the status that refuses it.

        A version no longer known, or an object that changed under it, gets
        404; a read that fails gets 502.

        Parameters
        ----------
        request
            The request, complete.

        Returns
        -------
        tuple[int, list[tuple[str, str]], bytes]
            The status, the headers and the body.
        """
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
            # RFC 9110, section 15.5.6: a 405 names the methods the target allows.
            return _answer_empty(asked.status, *([("allow", "GET")] if asked.status == 405 else []))
        cached = self._sources.get(asked.source)
        meta = cached.find_known(asked.version) if cached is not None else None
        if cached is None or meta is None:
            return _answer_empty(404)
        window = clamp(asked, meta.size)
        if window is None:
            return _answer_empty(416, ("content-range", f"bytes */{meta.size}"))
        offset, length = window
        try:
            data = await cached.at(meta).aread(offset, length)
        except ObjectChangedError:
            # The object changed under a version a reader still holds.
            return _answer_empty(404)
        except Exception as error:
            logger.warning(f"loopback range read failed with {type(error).__name__}")
            return _answer_empty(502)
        return 206, build_partial_headers(offset, len(data), meta.size), data


async def _read_next_request(
    connection: h11.Connection, reader: asyncio.StreamReader
) -> h11.Request | None:
    """Wait for the next request on the connection to be complete.

    Parameters
    ----------
    connection
        The h11 state of the connection.
    reader
        The stream the bytes arrive on.

    Returns
    -------
    h11.Request | None
        The request, or None when the peer has gone.
    """
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
    """Start the server of the running event loop at its first use, and return it.

    Returns
    -------
    RangeServer
        The server of this loop, listening.
    """
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
