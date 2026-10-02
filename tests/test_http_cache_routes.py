"""Cache headers and 304s on the tile and map routes.

``app.*`` is imported at the top of this module, nowhere else; where a
test patches a provider class or the settings, it looks the live one up
with ``importlib``.
"""

import importlib

import pytest
from pygeoapi.formats import FORMAT_TYPES
from starlette.testclient import TestClient

from app.pygeoapi.api_async.caching import HttpCache
from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config

MVT = "application/vnd.mapbox-vector-tile"
PUBLIC = HttpCache(max_age=300, protected=False, code="test")
TILE = "/collections/places/tiles/WebMercatorQuad/2/3/1"
ABSENT = "/collections/places/tiles/WebMercatorQuad/2/0/0"
OUTSIDE = "/collections/places/tiles/WebMercatorQuad/5/0/0"


def _tiles(path) -> dict:
    return {
        "type": "tile",
        "name": "app.provider.pmtiles.PMTilesProvider",
        "data": str(path),
        "options": {"zoom": {"min": 0, "max": 2}, "schemes": ["WebMercatorQuad"]},
        "format": {"name": "pbf", "mimetype": MVT},
    }


def _tiles_app(folder, *, gzip=False, **policy):
    archive = write_archive(
        folder / "places.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0), (2, 1, 3): TILE_BYTES(2, 1, 3)},
    )
    config = _config({"places": _collection("Places", [_tiles(archive)])})
    config["server"]["gzip"] = gzip
    return build_pygeoapi_subapp(config, build_openapi(config), **policy)


def _tiles_client(folder, http_cache=PUBLIC, *, gzip=False) -> TestClient:
    app = _tiles_app(folder, gzip=gzip, http_cache=http_cache)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    return _tiles_client(tmp_path_factory.mktemp("cached-tiles"))


@pytest.fixture
def gzip_client(tmp_path):
    """A client of a server with ``gzip: true``.

    pygeoapi turns gzip on for the whole process, in a module-level dict;
    the dict is put back as it was for the tests that follow.
    """
    formats = FORMAT_TYPES.copy()
    yield _tiles_client(tmp_path, gzip=True)
    FORMAT_TYPES.clear()
    FORMAT_TYPES.update(formats)


def _tile(client, path=TILE, headers=None):
    # The tileset links carry `?f=mvt`; without a format pygeoapi answers 400.
    return client.get(path, params={"f": "mvt"}, headers=headers)


def test_a_tile_carries_an_etag_and_how_long_to_keep_it(client):
    r = _tile(client)

    assert r.status_code == 200
    assert r.headers["etag"].startswith('"')
    assert r.headers["cache-control"] == "public, max-age=300"
    assert r.headers["vary"] == "Accept, Accept-Encoding"


def test_a_tile_asked_with_its_etag_is_304_without_being_read(client, monkeypatch):
    etag = _tile(client).headers["etag"]
    live = importlib.import_module("app.provider.pmtiles").PMTilesProvider
    original = live.aget_tiles
    reads = []

    async def spy(self, *args, **kwargs):
        reads.append(kwargs)
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(live, "aget_tiles", spy)
    r = _tile(client, headers={"If-None-Match": etag})

    assert (r.status_code, r.content, reads) == (304, b"", [])
    assert r.headers["etag"] == etag
    assert r.headers["cache-control"] == "public, max-age=300"
    assert "content-encoding" not in r.headers


def test_a_list_of_etags_or_a_weak_one_still_matches(client):
    etag = _tile(client).headers["etag"]

    r = _tile(client, headers={"If-None-Match": f'"other", W/{etag}'})

    assert r.status_code == 304


def test_another_etag_gets_the_tile(client):
    r = _tile(client, headers={"If-None-Match": '"other"'})

    assert (r.status_code, r.content) == (200, b"tile 2/1/3")


def test_an_absent_tile_is_204_with_an_etag_that_gives_a_304(client):
    r = _tile(client, ABSENT)

    assert r.status_code == 204
    assert r.headers["cache-control"] == "public, max-age=300"
    assert _tile(client, ABSENT, {"If-None-Match": r.headers["etag"]}).status_code == 304


def test_only_tiles_that_exist_or_are_absent_get_cache_headers(client):
    served, outside = _tile(client), _tile(client, OUTSIDE)

    assert "etag" in served.headers
    assert outside.status_code == 404
    assert "etag" not in outside.headers
    assert "cache-control" not in outside.headers


def test_a_star_on_a_tile_outside_the_limits_is_still_404(client):
    assert _tile(client, OUTSIDE, {"If-None-Match": "*"}).status_code == 404


def test_gzip_and_identity_answers_have_their_own_etags(gzip_client):
    gzipped = _tile(gzip_client)
    plain = _tile(gzip_client, headers={"Accept-Encoding": "identity"})

    assert gzipped.headers["content-encoding"] == "gzip"
    assert "content-encoding" not in plain.headers
    assert gzipped.headers["etag"] != plain.headers["etag"]


def test_the_304_of_a_gzip_server_has_no_body_and_no_content_coding(gzip_client):
    etag = _tile(gzip_client).headers["etag"]

    r = _tile(gzip_client, headers={"If-None-Match": etag})

    assert (r.status_code, r.content) == (304, b"")
    assert "content-encoding" not in r.headers


def test_a_head_request_gets_the_etag_and_the_304(client):
    etag = _tile(client).headers["etag"]

    head = client.head(TILE, params={"f": "mvt"})
    again = client.head(TILE, params={"f": "mvt"}, headers={"If-None-Match": etag})

    assert (head.status_code, head.headers["etag"]) == (200, etag)
    assert again.status_code == 304


def test_a_protected_instance_marks_its_tiles_private(tmp_path):
    client = _tiles_client(tmp_path, HttpCache(max_age=300, protected=True, code="test"))

    assert _tile(client).headers["cache-control"] == "private, max-age=300"


def test_a_max_age_of_zero_sends_no_cache_headers_and_no_304(tmp_path):
    client = _tiles_client(tmp_path, HttpCache(max_age=0, protected=False, code="test"))

    r = _tile(client, headers={"If-None-Match": "*"})

    assert r.status_code == 200
    assert "etag" not in r.headers
    assert "cache-control" not in r.headers


def test_without_a_policy_the_settings_decide(tmp_path, monkeypatch):
    settings = importlib.import_module("app.config.app").configuration
    monkeypatch.setattr(settings, "FASTGEOAPI_HTTP_MAX_AGE_SECONDS", 120)
    monkeypatch.setattr(settings, "API_KEY_ENABLED", True)

    client = TestClient(_tiles_app(tmp_path), raise_server_exceptions=False)

    assert _tile(client).headers["cache-control"] == "private, max-age=120"


def test_a_provider_without_a_version_gets_no_cache_headers(tmp_path):
    tiles = tmp_path / "tiles"
    (tiles / "0" / "0").mkdir(parents=True)
    (tiles / "0" / "0" / "0.pbf").write_bytes(b"\x1a\x03pbf")
    native = {
        "type": "tile",
        "name": "tests.test_tiles_async_route.NativeTiles",
        "data": str(tiles),
        "options": {"zoom": {"min": 0, "max": 5}, "schemes": ["WebMercatorQuad"]},
        "format": {"name": "pbf", "mimetype": MVT},
    }
    config = _config({"native": _collection("Native", [native])})
    app = build_pygeoapi_subapp(config, build_openapi(config), http_cache=PUBLIC)

    r = _tile(TestClient(app), "/collections/native/tiles/WebMercatorQuad/0/0/0")

    assert r.status_code == 200
    assert "etag" not in r.headers


def test_a_version_that_cannot_be_known_lets_the_tile_through(client, monkeypatch):
    live = importlib.import_module("app.provider.pmtiles").PMTilesProvider

    async def unreachable(self, **kwargs):
        raise OSError("the store is unreachable")

    monkeypatch.setattr(live, "aversion", unreachable)
    r = _tile(client)

    assert (r.status_code, r.content) == (200, b"tile 2/1/3")
    assert "etag" not in r.headers
