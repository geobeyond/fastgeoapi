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
    for header in ("content-type", "content-bbox"):
        assert native.headers.get(header) == threaded.headers.get(header)
    # pygeoapi lowercases the URI it was given; the native route writes the
    # provider's spelling of the same CRS.
    assert (native.headers.get("content-crs") or "").lower() == (
        threaded.headers.get("content-crs") or ""
    ).lower()


def test_a_map_past_max_size_answers_413(client):
    response = client.get("/collections/native/map", params={"width": 5000, "height": 64})

    assert response.status_code == 413
    assert "at most 2048" in response.text


def test_another_format_is_a_bad_parameter(client):
    response = client.get("/collections/native/map", params={"f": "jpeg"})

    assert response.status_code == 400


WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
EDGE = "20037508.342789244"
# pygeoapi's transform keeps latitudes within 85.0511 degrees of the equator.
TOP = "20037471.205137067"


def test_the_default_map_is_the_world_clipped(client):
    response = client.get("/collections/native/map", params={"width": 32, "height": 32})

    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-bbox"] == f"-{EDGE},-{TOP},{EDGE},{TOP}"


def test_a_clipped_map_reports_the_clipped_bbox(client):
    params = {"bbox": "-3e7,-1e6,3e7,1e6", "bbox-crs": WEB_MERCATOR, "width": 32, "height": 32}

    response = client.get("/collections/native/map", params=params)

    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-bbox"] == f"-{EDGE},-1000000.0,{EDGE},1000000.0"


def test_a_map_entirely_outside_answers_204(client):
    params = {"bbox": "-1e6,2.5e7,1e6,3e7", "bbox-crs": WEB_MERCATOR, "width": 32, "height": 32}

    response = client.get("/collections/native/map", params=params)

    assert (response.status_code, response.content) == (204, b"")


def test_the_route_refuses_before_the_provider(client):
    def drawn():
        return sum(len(renderer.requests) for renderer in FakeRenderer.instances)

    before = drawn()
    statuses = [
        client.get("/collections/native/map", params=params).status_code
        for params in ({"width": 0}, {"crs": CRS84}, {"f": "jpeg"}, {"width": 4096})
    ]

    assert statuses == [400, 400, 400, 413]
    assert drawn() == before


def test_without_storage_crs_the_map_is_drawn_in_the_first_crs(tmp_path):
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    archive = write_archive(tmp_path / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})
    definition = map_provider(archive)
    del definition["storage_crs"]
    config = _config({"roads": _collection("Roads", [definition])})
    client = TestClient(build_pygeoapi_subapp(config, build_openapi(config)))

    response = client.get("/collections/roads/map", params={"width": 16, "height": 16})

    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-crs"] == WEB_MERCATOR


def test_the_route_applies_the_ceiling(tmp_path):
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
    from app.pygeoapi.map_limits import MapCeiling

    archive = write_archive(tmp_path / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})
    config = _config({"roads": _collection("Roads", [map_provider(archive)])})
    ceiling = MapCeiling(1000, 1000)
    app = build_pygeoapi_subapp(
        config, build_openapi(config, map_ceiling=ceiling), map_ceiling=ceiling
    )
    client = TestClient(app, raise_server_exceptions=False)

    def status(width):
        return client.get("/collections/roads/map", params={"width": width, "height": 16})

    assert (status(1000).status_code, status(1001).status_code) == (200, 413)


def _gated_app(tmp_path, http_cache=None, **options):
    """A sub-app over one map collection whose fake renderer waits for its gate."""
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    archive = write_archive(
        tmp_path / "gated.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "gated", "vector_layers": [{"id": "roads"}]},
    )
    definition = map_provider(archive, fake="gate", **options)
    config = _config({"gated": _collection("Gated", [definition])})
    return build_pygeoapi_subapp(config, build_openapi(config), http_cache=http_cache), definition


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


def _occupied(provider) -> int:
    from app.pygeoapi.api_async.admission import admission_for

    return admission_for(provider, provider.limits).occupied


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
        # The first map takes the slot before the second one arrives, so the map
        # whose client leaves is the one waiting, not the one being drawn.
        await _until(lambda: _occupied(provider) == 1)
        abandoned = asyncio.create_task(_get(app, left))
        await _until(lambda: _occupied(provider) == 2)

        left.set()
        await _until(lambda: _occupied(provider) == 1)
        later = asyncio.create_task(_get(app))
        await _until(lambda: _occupied(provider) == 2)
    finally:
        FakeRenderer.gate.set()
    first, gone, second = await asyncio.gather(drawing, abandoned, later)

    assert (first["status"], second["status"]) == (200, 200)
    # Nginx's code for a client that closed the request; nobody reads it.
    assert gone["status"] == 499


@pytest.mark.asyncio
async def test_a_full_queue_answers_503_with_retry_after_and_no_cache_headers(tmp_path):
    import pygeoapi.plugin

    from app.pygeoapi.api_async.caching import HttpCache

    policy = HttpCache(max_age=300, protected=False, code="test")
    app, definition = _gated_app(tmp_path, http_cache=policy, queue=1, timeout=5)
    provider = pygeoapi.plugin.load_plugin("provider", definition)
    FakeRenderer.gate = asyncio.Event()
    try:
        drawing = asyncio.create_task(_get(app))
        waiting = asyncio.create_task(_get(app))
        await _until(lambda: _occupied(provider) == 2)
        busy = await _get(app)
    finally:
        FakeRenderer.gate.set()
    drawn, _ = await asyncio.gather(drawing, waiting)

    assert busy["status"] == 503
    assert dict(busy["headers"]).get(b"retry-after") == b"5"
    assert b"etag" in dict(drawn["headers"])
    assert b"etag" not in dict(busy["headers"])


@pytest.mark.asyncio
async def test_a_slow_map_answers_504_and_its_render_goes_on(tmp_path):
    import pygeoapi.plugin

    app, definition = _gated_app(tmp_path, timeout=0.05, render_limit=5)
    provider = pygeoapi.plugin.load_plugin("provider", definition)
    FakeRenderer.gate = asyncio.Event()
    try:
        slow = await _get(app)
        renderer = FakeRenderer.instances[-1]
        # The render goes on, so the tiles it reads stay cached for the next maps.
        assert not renderer.closed and provider.renderer_is_built
    finally:
        FakeRenderer.gate.set()
    await _until(lambda: _occupied(provider) == 0)
    again = await _get(app)

    assert (slow["status"], again["status"]) == (504, 200)
    assert FakeRenderer.instances[-1] is renderer
    assert renderer.calls == 2


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
    from tests.loop_guard import loop_guard

    with loop_guard():
        response = client.get("/collections/native/map", params={"width": 16, "height": 16})

    assert response.status_code == 200


def test_a_map_of_a_collection_with_time_has_content_datetime(tmp_path):
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    archive = write_archive(tmp_path / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})
    collection = _collection("Roads", [map_provider(archive)])
    collection["extents"]["temporal"] = {"begin": "2020-01-01T00:00:00Z", "end": None}
    config = _config({"roads": collection})
    client = TestClient(build_pygeoapi_subapp(config, build_openapi(config)))

    response = client.get("/collections/roads/map", params={"width": 16, "height": 16})

    assert response.status_code == 200, response.text[:200]
    assert response.headers["content-datetime"] == "2020-01-01T00:00:00Z/.."


def test_a_map_without_time_has_no_content_datetime(client):
    response = client.get("/collections/native/map", params={"width": 16, "height": 16})

    assert response.status_code == 200, response.text[:200]
    assert "content-datetime" not in response.headers
