"""The PMTiles provider through the whole stack: routes, registry, conformance, tile bytes awaited."""

import importlib
import re
import threading

import pytest
from blockbuster import blockbuster_ctx
from starlette.testclient import TestClient

from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config, _get

MVT = "application/vnd.mapbox-vector-tile"


def _provider(path) -> dict:
    return {
        "type": "tile",
        "name": "app.provider.pmtiles.PMTilesProvider",
        "data": str(path),
        "options": {"zoom": {"min": 0, "max": 2}, "schemes": ["WebMercatorQuad"]},
        "format": {"name": "pbf", "mimetype": MVT},
    }


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    path = write_archive(
        tmp_path_factory.mktemp("pmtiles") / "places.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0), (2, 1, 3): TILE_BYTES(2, 1, 3)},
        metadata={
            "name": "Places",
            "vector_layers": [{"id": "place", "minzoom": 0, "maxzoom": 2}],
        },
    )
    config = _config({"places": _collection("Places", [_provider(path)])})
    return TestClient(
        build_pygeoapi_subapp(config, build_openapi(config)), raise_server_exceptions=False
    )


def test_a_tile_comes_back_decompressed(client):
    r = _get(client, "/collections/places/tiles/WebMercatorQuad/2/3/1")
    assert (r.status_code, r.content, r.headers["content-type"]) == (200, b"tile 2/1/3", MVT)


def test_absent_within_limits_is_204_and_outside_is_404(client):
    assert _get(client, "/collections/places/tiles/WebMercatorQuad/2/0/0").status_code == 204
    assert _get(client, "/collections/places/tiles/WebMercatorQuad/5/0/0").status_code == 404


def test_the_tile_is_awaited_on_the_loop_without_blocking(client, monkeypatch):
    threads = []
    # pygeoapi's `load_plugin` imports the provider by name, so the live
    # instance belongs to whatever `app.provider.pmtiles` is in
    # `sys.modules` now; after another module purged `app.*`, that is not
    # the class this file bound at import. Patch the live one.
    live = importlib.import_module("app.provider.pmtiles").PMTilesProvider
    original = live.aget_tiles

    async def spy(self, *args, **kwargs):
        threads.append(threading.current_thread().name)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(live, "aget_tiles", spy)
    # Warm-up: the capability probe and the archive open run once, off the loop.
    _get(client, "/collections/places/tiles/WebMercatorQuad/0/0/0")
    with blockbuster_ctx():
        r = _get(client, "/collections/places/tiles/WebMercatorQuad/2/3/1")
    assert r.status_code == 200
    assert threads
    assert not any(re.fullmatch(r"asyncio_\d+", name) for name in threads)


def test_tilesets_and_tilejson_are_served(client):
    tilesets = client.get("/collections/places/tiles?f=json")
    assert tilesets.status_code == 200, tilesets.text[:300]
    body = tilesets.json()
    assert body["tilesets"][0]["crs"] == "http://www.opengis.net/def/crs/EPSG/0/3857"
    assert any(link["rel"] == "item" for link in body["links"])
    tilejson = client.get("/collections/places/tiles/WebMercatorQuad/metadata?f=tilejson")
    assert tilejson.status_code == 200, tilejson.text[:300]
    assert tilejson.json()["vector_layers"][0]["id"] == "place"


def test_conformance_declares_tiles(client):
    classes = client.get("/conformance?f=json").json()["conformsTo"]
    assert any("ogcapi-tiles-1/1.0/conf/core" in c for c in classes), classes
