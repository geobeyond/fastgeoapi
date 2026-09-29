"""/map: a native map provider is awaited, the others keep pygeoapi's threadpool.

``SyncMaps`` lives here and is loaded by dotted path, like the tile test's
``NativeTiles``: it answers through pygeoapi's own ``get_collection_map``,
and the parity tests compare the two routes on the same requests.
"""

import asyncio

import pytest
from pygeoapi.provider.base import BaseProvider
from starlette.testclient import TestClient

from tests.maps_fixtures import FakeRenderer, map_provider, tiny_png
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config


class SyncMaps(BaseProvider):
    """A map provider pygeoapi calls in the threadpool, drawing what the fake draws."""

    def query(self, width=500, height=300, **kwargs):
        return tiny_png(int(width), int(height))


def _sync_provider() -> dict:
    return {
        "type": "map",
        "name": "tests.test_maps_async_route.SyncMaps",
        "data": "unused",
        "storage_crs": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "format": {"name": "png", "mimetype": "image/png"},
    }


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    folder = tmp_path_factory.mktemp("maps")
    archive = write_archive(
        folder / "roads.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "roads", "vector_layers": [{"id": "roads"}]},
    )
    night = folder / "night.json"
    night.write_text(
        '{"version": 8, "sources": {}, "layers": [{"id": "night", "type": "background"}]}'
    )
    config = _config(
        {
            "native": _collection("Native", [map_provider(archive, styles={"night": str(night)})]),
            "threaded": _collection("Threaded", [_sync_provider()]),
        }
    )
    return TestClient(
        build_pygeoapi_subapp(config, build_openapi(config)), raise_server_exceptions=False
    )


def test_a_native_provider_is_awaited(client):
    response = client.get(
        "/collections/native/map", params={"bbox": "12.4,41.8,12.6,42.0", "width": 64, "height": 48}
    )

    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-crs"] == "http://www.opengis.net/def/crs/EPSG/0/3857"
    assert FakeRenderer.instances[-1].requests[-1].width == 64


def test_a_map_without_bbox_is_the_world(client):
    response = client.get("/collections/native/map", params={"width": 32, "height": 32})

    assert response.status_code == 200, response.text[:200]


def test_an_unknown_style_answers_404(client):
    response = client.get("/collections/native/styles/missing/map")

    assert response.status_code == 404
    assert "style missing not found" in response.text


def test_a_named_style_is_drawn_on_the_styled_route(client):
    response = client.get(
        "/collections/native/styles/night/map",
        params={"width": 16, "height": 16, "transparent": "false"},
    )

    assert response.status_code == 200, response.text[:200]
    assert FakeRenderer.instances[-1].requests[-1].style["layers"][0]["id"] == "night"


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"bbox": "12.4,41.8,12.6,42.0", "width": 64, "height": 48},
        {"bbox": "12.4,41.8,12.6"},
        {"bbox": "a,b,c,d"},
        {"width": "wide"},
        {"crs": "http://www.opengis.net/def/crs/EPSG/0/3857"},
        {"crs": "EPSG:3857"},
    ],
)
def test_the_native_route_answers_like_pygeoapi(client, params):
    native = client.get("/collections/native/map", params=params)
    threaded = client.get("/collections/threaded/map", params=params)

    assert native.status_code == threaded.status_code
    for header in ("content-type", "content-crs", "content-bbox"):
        assert native.headers.get(header) == threaded.headers.get(header)


def test_a_map_past_max_size_answers_413(client):
    response = client.get("/collections/native/map", params={"width": 5000, "height": 64})

    assert response.status_code == 413
    assert "at most 2048" in response.text


def test_another_format_is_a_bad_parameter(client):
    response = client.get("/collections/native/map", params={"f": "jpeg"})

    assert response.status_code == 400


def _gated_app(tmp_path, **options):
    """A sub-app over one map collection whose fake renderer waits for its gate."""
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    archive = write_archive(
        tmp_path / "gated.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "gated", "vector_layers": [{"id": "roads"}]},
    )
    definition = map_provider(archive, fake="gate", **options)
    config = _config({"gated": _collection("Gated", [definition])})
    return build_pygeoapi_subapp(config, build_openapi(config)), definition


async def _get(app, left: asyncio.Event | None = None) -> dict:
    """One map through the ASGI app; setting ``left`` is its client going away."""
    left = left or asyncio.Event()
    sent: list[dict] = []
    requested = False

    async def receive():
        nonlocal requested
        if not requested:
            requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await left.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/collections/gated/map",
        "raw_path": b"/collections/gated/map",
        "root_path": "",
        "query_string": b"width=16&height=16",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    await app(scope, receive, send)
    return next(message for message in sent if message["type"] == "http.response.start")


async def _until(condition, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "the provider never reached the expected state"
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_a_map_whose_client_left_gives_its_place_in_the_queue_back(tmp_path):
    import pygeoapi.plugin

    app, definition = _gated_app(tmp_path, queue=1, timeout=5)
    provider = pygeoapi.plugin.load_plugin("provider", definition)
    FakeRenderer.gate = asyncio.Event()
    left = asyncio.Event()
    try:
        drawing = asyncio.create_task(_get(app))
        abandoned = asyncio.create_task(_get(app, left))
        await _until(lambda: provider.waiting == 2)

        left.set()
        await _until(lambda: provider.waiting == 1)
        later = asyncio.create_task(_get(app))
        await _until(lambda: provider.waiting == 2)
    finally:
        FakeRenderer.gate.set()
    first, gone, second = await asyncio.gather(drawing, abandoned, later)

    assert (first["status"], second["status"]) == (200, 200)
    # Nginx's code for a client that closed the request; nobody reads it.
    assert gone["status"] == 499


@pytest.mark.asyncio
async def test_a_full_queue_answers_503_with_retry_after(tmp_path):
    import pygeoapi.plugin

    app, definition = _gated_app(tmp_path, queue=1, timeout=5)
    provider = pygeoapi.plugin.load_plugin("provider", definition)
    FakeRenderer.gate = asyncio.Event()
    try:
        drawing = asyncio.create_task(_get(app))
        waiting = asyncio.create_task(_get(app))
        await _until(lambda: provider.waiting == 2)
        busy = await _get(app)
    finally:
        FakeRenderer.gate.set()
    await asyncio.gather(drawing, waiting)

    assert busy["status"] == 503
    assert dict(busy["headers"]).get(b"retry-after") == b"5"


def _behind_opa_and_the_proxy(app):
    """The chain of OPA_ENABLED with FASTGEOAPI_REVERSE_PROXY: OPA's buffering receive,
    then the proxy's BaseHTTPMiddleware, then the sub-app."""
    from fastapi_opa.opa.opa_middleware import OwnReceive

    from app.middleware.proxy import ForwardedLinksMiddleware

    proxied = ForwardedLinksMiddleware(app)

    async def opa(scope, receive, send):
        await proxied(scope, OwnReceive(receive), send)

    return opa


@pytest.mark.asyncio
async def test_a_map_behind_opa_and_the_proxy_is_drawn(tmp_path):
    """OPA's receive hands the body out again and the proxy raises on it; the map is drawn."""
    app, _ = _gated_app(tmp_path)

    answer = await asyncio.wait_for(_get(_behind_opa_and_the_proxy(app)), timeout=10)

    assert answer["status"] == 200


def test_the_native_provider_blocks_nothing_on_the_loop(client):
    from blockbuster import blockbuster_ctx

    with blockbuster_ctx():
        response = client.get("/collections/native/map", params={"width": 16, "height": 16})

    assert response.status_code == 200
