"""Tile data: a native provider is awaited, everyone else keeps pygeoapi's threadpool (ADR-0010, decision 5).

``NativeTiles`` lives here and is loaded by dotted path: ``tests`` is a
package, so ``tests.test_tiles_async_route.NativeTiles`` resolves through
pygeoapi's ``load_plugin`` like any third-party provider would.
"""

import re
import threading

import pytest
from blockbuster import blockbuster_ctx
from pygeoapi.provider.base import ProviderQueryError
from pygeoapi.provider.base_mvt import BaseMVTProvider
from pygeoapi.provider.tile import ProviderTileNotFoundError
from starlette.testclient import TestClient

from app.provider.base import AsyncProviderMixin
from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

TILE = b"\x1a\x03pbf"
MVT = "application/vnd.mapbox-vector-tile"


class NativeTiles(AsyncProviderMixin, BaseMVTProvider):
    """A native tile provider whose sync face must never be touched by the route."""

    THREAD_SAFE = True
    native_async = True
    threads: list[str] = []

    def get_layer(self):
        return "native"

    def get_tiles_service(self, baseurl=None, servicepath=None, dirpath=None, tile_type=None):
        self._service_url = f"{baseurl}{servicepath}"
        return self.get_tms_links()

    def get_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        raise AssertionError("the sync face must not be used for a native provider")

    async def aget_tiles(self, layer, tileset, z, y, x, format_):
        NativeTiles.threads.append(threading.current_thread().name)
        if int(z) == 4:
            return None
        if int(z) == 5:
            raise ProviderTileNotFoundError("gone")
        if int(z) == 6:
            raise ProviderQueryError("engine down")
        return f"{layer}:{tileset}:{z}/{x}/{y}:{format_}".encode()


def _tile_provider(name: str, data: str) -> dict:
    return {
        "type": "tile",
        "name": name,
        "data": data,
        "options": {"zoom": {"min": 0, "max": 5}, "schemes": ["WebMercatorQuad"]},
        "format": {"name": "pbf", "mimetype": MVT},
    }


def _collection(title: str, providers: list[dict]) -> dict:
    return {
        "type": "collection",
        "title": {"en": title},
        "description": {"en": title},
        "keywords": {"en": [title]},
        "extents": {
            "spatial": {
                "bbox": [-180, -90, 180, 90],
                "crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
            }
        },
        "links": [],
        "providers": providers,
    }


def _config(resources: dict) -> dict:
    return {
        "server": {
            "bind": {"host": "0.0.0.0", "port": 5000},
            "url": "http://localhost:5000",
            "mimetype": "application/json; charset=UTF-8",
            "encoding": "utf-8",
            "language": "en-US",
            "map": {
                "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
                "attribution": "OSM",
            },
        },
        "logging": {"level": "ERROR"},
        "metadata": {
            "identification": {
                "title": {"en": "tiles test"},
                "description": {"en": "tiles test"},
                "keywords": {"en": ["tiles"]},
                "keywords_type": "theme",
                "terms_of_service": "https://creativecommons.org/licenses/by/4.0/",
                "url": "https://example.org",
            },
            "license": {
                "name": "CC-BY 4.0",
                "url": "https://creativecommons.org/licenses/by/4.0/",
            },
            "provider": {"name": "geobeyond", "url": "https://geobeyond.it"},
            "contact": {"name": "test", "email": "test@example.org"},
        },
        "resources": resources,
    }


def _client(config: dict) -> TestClient:
    return TestClient(
        build_pygeoapi_subapp(config, build_openapi(config)), raise_server_exceptions=False
    )


def _get(client: TestClient, path: str):
    # pygeoapi's tile handler answers 400 without an explicit format: the
    # tileset links it publishes carry `?f=mvt`, so clients always send it.
    return client.get(path, params={"f": "mvt"})


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    tiles = tmp_path_factory.mktemp("tiles")
    (tiles / "0" / "0").mkdir(parents=True)
    (tiles / "0" / "0" / "0.pbf").write_bytes(TILE)
    (tiles / "metadata.json").write_text("{}")
    config = _config(
        {
            "roads": _collection("Roads", [_tile_provider("MVT-tippecanoe", str(tiles))]),
            "native": _collection(
                "Native",
                [_tile_provider("tests.test_tiles_async_route.NativeTiles", "memory://native")],
            ),
        }
    )
    return _client(config)


def test_a_sync_provider_still_goes_through_pygeoapi(client):
    r = _get(client, "/collections/roads/tiles/WebMercatorQuad/0/0/0")
    assert (r.status_code, r.content, r.headers["content-type"]) == (200, TILE, MVT)


def test_a_missing_tile_within_limits_is_204_as_upstream(client):
    r = _get(client, "/collections/roads/tiles/WebMercatorQuad/1/0/1")
    assert (r.status_code, r.content) == (204, b"")


def test_a_tile_out_of_limits_is_404_as_upstream(client):
    r = _get(client, "/collections/roads/tiles/WebMercatorQuad/7/0/0")
    assert (r.status_code, r.text) == (404, "Tile not found")


def test_a_native_provider_is_awaited_on_the_loop_not_in_the_pool(client):
    NativeTiles.threads.clear()
    r = _get(client, "/collections/native/tiles/WebMercatorQuad/3/2/1")
    assert (r.status_code, r.content, r.headers["content-type"]) == (
        200,
        b"native:WebMercatorQuad:3/1/2:pbf",
        MVT,
    )
    # The default executor names its workers `asyncio_<n>`; the loop thread
    # under TestClient is anyio's `asyncio-portal-<id>`, under uvicorn the
    # main thread. A coroutine cannot run in a worker anyway: this pins
    # the naming so a future `to_thread` in the route would show up here.
    assert NativeTiles.threads
    assert not any(re.fullmatch(r"asyncio_\d+", name) for name in NativeTiles.threads)


def test_a_native_none_is_204(client):
    r = _get(client, "/collections/native/tiles/WebMercatorQuad/4/0/0")
    assert (r.status_code, r.content) == (204, b"")


def test_a_native_not_found_is_404(client):
    r = _get(client, "/collections/native/tiles/WebMercatorQuad/5/0/0")
    assert (r.status_code, r.text) == (404, "Tile not found")


def test_a_native_provider_error_maps_by_its_status_code(client):
    r = _get(client, "/collections/native/tiles/WebMercatorQuad/6/0/0")
    assert r.status_code == 500
    assert r.json()["code"] == "NoApplicableCode"


def test_the_native_route_makes_no_blocking_call_on_the_loop(client):
    # Warm-up: the capability probe instantiates the provider off the loop
    # once per collection; from then on a native tile is pure `await`.
    _get(client, "/collections/native/tiles/WebMercatorQuad/1/0/0")
    with blockbuster_ctx():
        r = _get(client, "/collections/native/tiles/WebMercatorQuad/2/1/1")
    assert r.status_code == 200


def test_an_unknown_collection_is_404_as_upstream(client):
    r = _get(client, "/collections/nowhere/tiles/WebMercatorQuad/0/0/0")
    assert r.status_code == 404


def test_without_tiles_in_the_config_the_route_is_not_mounted(tmp_path):
    # One feature at least: pygeoapi's GeoJSON provider reads the fields
    # off `features[0]` while the OpenAPI document is built.
    (tmp_path / "x.geojson").write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature", "id": 1,'
        ' "properties": {"id": 1, "name": "a"}, "geometry": {"type": "Point", "coordinates": [0, 0]}}]}'
    )
    feature = {
        "type": "feature",
        "name": "GeoJSON",
        "data": str(tmp_path / "x.geojson"),
        "id_field": "id",
    }
    config = _config({"plain": _collection("Plain", [feature])})
    r = _get(_client(config), "/collections/plain/tiles/WebMercatorQuad/0/0/0")
    assert r.status_code == 404
