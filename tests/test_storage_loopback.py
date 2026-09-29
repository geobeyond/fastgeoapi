"""Cached ranges served to readers on this machine, over HTTP on loopback."""

import asyncio
from dataclasses import replace

import httpx
import pytest

from tests.range_cache_fixtures import CountingStore, memory_store, range_cache

BLOB = bytes(range(256)) * 4
KEY = "tiles/roads.pmtiles"


class _NoEtag(CountingStore):
    """A store without ETags, like some HTTP servers; CountingStore gives it the whole protocol."""

    def head(self, path):
        return replace(super().head(path), etag=None)

    async def ahead(self, path):
        return replace(await super().ahead(path), etag=None)


async def _serve(origin=None):
    from app.provider.storage import CachedRanges
    from app.provider.storage.loopback import RangeServer, RangeSources

    if origin is None:
        origin = CountingStore(memory_store())
        origin.put(KEY, BLOB)
    cached = CachedRanges(origin, KEY, range_cache(memory_store()), source=f"s3://bucket/{KEY}")
    sources = RangeSources()
    sources.register(cached)
    server = RangeServer(sources)
    await server.start()
    return server, cached, origin


async def _raw_get(port, path, range_header):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(
        f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nRange: {range_header}\r\n"
        "Connection: close\r\n\r\n".encode()
    )
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


def test_a_range_request_is_parsed():
    from app.provider.storage.loopback import RangeRequest, parse_request

    assert parse_request("GET", "/tok/src/ver", "bytes=0-126", token="tok") == RangeRequest(
        "src", "ver", 0, 126
    )


@pytest.mark.parametrize(
    ("method", "target", "header", "status"),
    [
        ("POST", "/tok/src/ver", "bytes=0-1", 405),
        ("HEAD", "/tok/src/ver", "bytes=0-1", 405),
        ("GET", "/bad/src/ver", "bytes=0-1", 404),
        ("GET", "/tok/src", "bytes=0-1", 404),
        ("GET", "/tok/src/ver/extra", "bytes=0-1", 404),
        ("GET", "/tok/src/ver", None, 416),
        ("GET", "/tok/src/ver", "bytes=5-", 416),
        ("GET", "/tok/src/ver", "bytes=0-1,4-5", 416),
        ("GET", "/tok/src/ver", "bytes=9-3", 416),
    ],
)
def test_what_the_server_refuses(method, target, header, status):
    from app.provider.storage.loopback import Refusal, parse_request

    assert parse_request(method, target, header, token="tok") == Refusal(status)


def test_a_range_past_the_end_is_cut_or_refused():
    from app.provider.storage.loopback import RangeRequest, clamp

    assert clamp(RangeRequest("s", "v", 90, 200), size=100) == (90, 10)
    assert clamp(RangeRequest("s", "v", 100, 200), size=100) is None


def test_the_partial_headers_describe_the_range():
    from app.provider.storage.loopback import partial_headers

    headers = dict(partial_headers(10, 5, 100))
    assert headers["content-range"] == "bytes 10-14/100"
    assert headers["content-length"] == "5"


@pytest.mark.asyncio
async def test_a_registered_object_is_served_by_range_on_one_connection():
    server, cached, _ = await _serve()
    url = server.url_for(cached, await cached.ameta())
    try:
        async with httpx.AsyncClient() as client:
            first = await client.get(url, headers={"Range": "bytes=0-126"})
            second = await client.get(url, headers={"Range": "bytes=127-168"})
    finally:
        await server.aclose()

    assert (first.status_code, first.content) == (206, BLOB[:127])
    assert first.headers["content-range"] == f"bytes 0-126/{len(BLOB)}"
    assert (second.status_code, second.content) == (206, BLOB[127:169])
    assert server.connections == 1


@pytest.mark.asyncio
async def test_the_server_listens_on_loopback_only():
    server, cached, _ = await _serve()
    try:
        assert server.url_for(cached, await cached.ameta()).startswith("http://127.0.0.1:")
        assert {sock.getsockname()[0] for sock in server.sockets} == {"127.0.0.1"}
    finally:
        await server.aclose()


@pytest.mark.asyncio
async def test_a_wrong_token_an_unknown_source_and_an_unknown_version_get_the_same_404():
    from app.provider.storage.cache import version_of

    server, cached, _ = await _serve()
    version = version_of(await cached.ameta())
    base = f"http://127.0.0.1:{server.port}"
    paths = [
        f"/wrong/{cached.source}/{version}",
        f"/{server.token}/unknown/{version}",
        f"/{server.token}/{cached.source}/unknown",
    ]
    try:
        async with httpx.AsyncClient() as client:
            responses = [
                await client.get(base + path, headers={"Range": "bytes=0-9"}) for path in paths
            ]
    finally:
        await server.aclose()

    assert [(response.status_code, response.content) for response in responses] == [(404, b"")] * 3


@pytest.mark.asyncio
async def test_a_range_past_the_end_of_the_object_answers_416():
    server, cached, _ = await _serve()
    url = server.url_for(cached, await cached.ameta())
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                url, headers={"Range": f"bytes={len(BLOB)}-{len(BLOB) + 9}"}
            )
    finally:
        await server.aclose()

    assert response.status_code == 416
    assert response.headers["content-range"] == f"bytes */{len(BLOB)}"


@pytest.mark.asyncio
async def test_a_stale_version_that_misses_answers_404_and_forgets_the_version():
    server, cached, origin = await _serve()
    url = server.url_for(cached, await cached.ameta())
    origin.put(KEY, bytes(len(BLOB)))  # the renderer still holds the old URL
    heads = origin.heads
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers={"Range": "bytes=0-9"})
    finally:
        await server.aclose()

    assert response.status_code == 404
    await cached.ameta()
    assert origin.heads == heads + 1


@pytest.mark.asyncio
async def test_an_object_without_etag_is_served_unversioned():
    origin = CountingStore(memory_store())
    origin.put(KEY, BLOB)
    server, cached, _ = await _serve(_NoEtag(origin))
    url = server.url_for(cached, await cached.ameta())
    try:
        async with httpx.AsyncClient() as client:
            first = await client.get(url, headers={"Range": "bytes=0-9"})
            second = await client.get(url, headers={"Range": "bytes=0-9"})
    finally:
        await server.aclose()

    assert url.endswith("/unversioned")
    assert (first.status_code, first.content, second.content) == (206, BLOB[:10], BLOB[:10])
    assert origin.range_reads == [(0, 10), (0, 10)]


@pytest.mark.asyncio
async def test_the_token_never_reaches_the_log():
    from loguru import logger

    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="DEBUG")

    class _Failing(CountingStore):
        async def aget_range(self, *args, **kwargs):
            raise OSError("the bucket is gone")

    origin = _Failing(memory_store())
    origin.put(KEY, BLOB)
    server, cached, _ = await _serve(origin)
    url = server.url_for(cached, await cached.ameta())
    try:
        async with httpx.AsyncClient() as client:
            failed = await client.get(url, headers={"Range": "bytes=0-9"})
            await client.get(
                f"http://127.0.0.1:{server.port}/{server.token}/x/y", headers={"Range": "bytes=0-9"}
            )
    finally:
        await server.aclose()
        logger.remove(sink)

    assert failed.status_code == 502
    assert messages
    assert all(server.token not in message for message in messages)


@pytest.mark.asyncio
async def test_serving_a_range_never_blocks_the_loop(tmp_path):
    from blockbuster import blockbuster_ctx

    from app.provider.storage import CachedRanges, RangeCache, load_store
    from app.provider.storage.loopback import RangeServer, RangeSources

    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "roads.pmtiles").write_bytes(BLOB)
    origin = load_store(str(tmp_path / "data"))
    cached = CachedRanges(
        origin,
        "roads.pmtiles",
        RangeCache.at(str(tmp_path / "cache"), max_bytes=1 << 20),
        source="x",
    )
    sources = RangeSources()
    sources.register(cached)
    server = RangeServer(sources)
    await server.start()
    url_path = server.url_for(cached, await cached.ameta()).split(str(server.port), 1)[1]
    try:
        with blockbuster_ctx():
            response = await _raw_get(server.port, url_path, "bytes=0-9")
    finally:
        await server.aclose()
        await cached.cache.drain()

    assert response.startswith(b"HTTP/1.1 206")
    assert response.endswith(BLOB[:10])


@pytest.mark.asyncio
async def test_one_server_per_loop_until_it_is_closed():
    from app.provider.storage.loopback import close_range_server, ensure_range_server

    first = await ensure_range_server()
    assert await ensure_range_server() is first
    assert first.port
    await close_range_server()
    second = await ensure_range_server()
    assert second is not first
    await close_range_server()


@pytest.mark.asyncio
async def test_the_app_lifespan_closes_the_loopback_server():
    from unittest.mock import AsyncMock, patch

    from app import main

    app = main.create_app()
    # The loopback module main itself imported: after a purge of sys.modules
    # a fresh import of it would be another module object.
    with patch.object(main.loopback, "close_range_server", AsyncMock()) as close:
        async with app.router.lifespan_context(app):
            pass
    close.assert_awaited_once()
