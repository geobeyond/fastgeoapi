"""/map: a native map provider is awaited, the others keep pygeoapi's threadpool.

``SyncMaps`` lives here and is loaded by dotted path, like the tile test's
``NativeTiles``: it answers through pygeoapi's own ``get_collection_map``,
and the parity tests compare the two routes on the same requests.
"""

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


def test_another_format_is_a_bad_parameter(client):
    response = client.get("/collections/native/map", params={"f": "jpeg"})

    assert response.status_code == 400


def test_the_native_provider_blocks_nothing_on_the_loop(client):
    from blockbuster import blockbuster_ctx

    with blockbuster_ctx():
        response = client.get("/collections/native/map", params={"width": 16, "height": 16})

    assert response.status_code == 200
