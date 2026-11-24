"""The martin tile provider (app/provider/martin.py): alone, through the tile routes, in the app.

Its config translation, which needs no martin-py, is in `test_martin_config.py`.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import shutil
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml
from pygeoapi.provider.tile import ProviderTileNotFoundError
from starlette.testclient import TestClient

pytest.importorskip("martin_py", reason="the martin provider needs the `martin` extra")

from app.provider.martin import MartinTilesProvider
from app.tiles.contract import TileOutsideError, TileSourceError

FIXTURE_GEOJSON = Path(__file__).parent / "data" / "martin" / "feature_collection.geojson"
MVT = "application/vnd.mapbox-vector-tile"


def _provider_def(data: Path | str, **options) -> dict:
    return {
        "type": "tile",
        "name": "app.provider.martin.MartinTilesProvider",
        "data": str(data),
        "options": {"zoom": {"min": 0, "max": 14}, "schemes": ["WebMercatorQuad"], **options},
        "format": {"name": "pbf", "mimetype": MVT},
    }


@pytest.fixture
def geojson(tmp_path) -> Path:
    path = tmp_path / "rome.geojson"
    shutil.copy(FIXTURE_GEOJSON, path)
    return path


def test_building_the_provider_loads_nothing(geojson):
    provider = MartinTilesProvider(_provider_def(geojson))
    assert provider.source._loaded is None
    assert provider.get_layer() == "rome"


def test_both_faces_serve_the_same_tile(geojson):
    provider = MartinTilesProvider(_provider_def(geojson))
    tile = provider.get_tiles(z=0, x=0, y=0)
    assert tile
    assert asyncio.run(provider.aget_tiles(z=0, x=0, y=0)) == tile


def test_a_tile_without_data_is_none_and_outside_the_limits_is_404(geojson):
    provider = MartinTilesProvider(_provider_def(geojson))
    assert provider.get_tiles(z=14, x=0, y=0) is None
    with pytest.raises(ProviderTileNotFoundError):
        provider.get_tiles(z=15, x=0, y=0)


def test_layer_id_option_names_the_layer(geojson):
    provider = MartinTilesProvider(_provider_def(geojson, layer_id="places"))
    assert provider.get_layer() == "places"
    tilejson = provider.get_vendor_metadata(
        "c", "http://h", None, "WebMercatorQuad", None, None, None
    )
    assert [layer["id"] for layer in tilejson["vector_layers"]] == ["places"]


def test_tilejson_comes_from_martin(geojson):
    provider = MartinTilesProvider(_provider_def(geojson))
    tilejson = provider.get_vendor_metadata(
        "rome", "http://h/geoapi", None, "WebMercatorQuad", None, None, None
    )
    assert tilejson["tiles"] == [
        "http://h/geoapi/collections/rome/tiles/WebMercatorQuad/{z}/{y}/{x}?f=mvt"
    ]
    assert tilejson["vector_layers"][0]["fields"] == {"name": "String"}
    assert (tilejson["minzoom"], tilejson["maxzoom"]) == (0, 14)


def test_a_changed_file_is_loaded_again_with_a_new_version(geojson):
    provider = MartinTilesProvider(_provider_def(geojson))
    provider.get_tiles(z=0, x=0, y=0)
    first, version = provider.source._loaded, asyncio.run(provider.aversion(z=0, x=0, y=0))
    os.utime(geojson, ns=(1, 1))
    provider.get_tiles(z=0, x=0, y=0)
    assert provider.source._loaded is not first
    assert asyncio.run(provider.aversion(z=0, x=0, y=0)) not in (None, version)


def test_a_version_that_cannot_be_read_serves_tiles_without_one(geojson):
    """The store asking the version may fail where martin's own reader works."""
    provider = MartinTilesProvider(_provider_def(f"s3://bucket/{geojson.name}"))

    def refused():
        raise ValueError("Configuration key: 'scope' is not valid for store 'S3'")

    with mock.patch("app.provider.martin.is_remote", return_value=True):
        object.__setattr__(provider.source._context, "cached", refused)
        assert asyncio.run(provider.aversion(z=0, x=0, y=0)) is None
        assert provider.source.data_version() is None
    assert not provider.source._follows_version


def test_a_glob_has_no_version():
    provider = MartinTilesProvider(_provider_def("s3://bucket/prefix/*.parquet"))
    assert asyncio.run(provider.aversion(z=0, x=0, y=0)) is None


def test_a_source_martin_cannot_load_is_a_source_error(tmp_path):
    provider = MartinTilesProvider(_provider_def(tmp_path / "missing.geojson"))
    with pytest.raises(TileSourceError):
        provider.source.tile(0, 0, 0)


def test_martin_errors_are_mapped_by_who_is_at_fault(geojson):
    import martin_py

    source = MartinTilesProvider(_provider_def(geojson)).source
    assert isinstance(source._tile_error(ValueError("bad"), 0, 0, 0), TileOutsideError)
    assert isinstance(
        source._tile_error(martin_py.TileRequestError("zoom"), 0, 0, 0), TileOutsideError
    )
    failure = source._tile_error(martin_py.TileFetchError("s3://secret"), 0, 0, 0)
    assert isinstance(failure, TileSourceError)
    assert "secret" not in str(failure)


# --- through the routes --------------------------------------------------------


@pytest.fixture
def client(geojson) -> TestClient:
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
    from tests.test_tiles_async_route import _collection, _config

    config = _config({"rome": _collection("Rome", [_provider_def(geojson)])})
    return TestClient(
        build_pygeoapi_subapp(config, build_openapi(config)), raise_server_exceptions=False
    )


def test_the_route_serves_martin_tiles(client):
    from tests.test_tiles_async_route import _get

    r = _get(client, "/collections/rome/tiles/WebMercatorQuad/0/0/0")
    assert (r.status_code, r.headers["content-type"]) == (200, MVT)
    assert r.content
    assert _get(client, "/collections/rome/tiles/WebMercatorQuad/14/0/0").status_code == 204
    assert _get(client, "/collections/rome/tiles/WebMercatorQuad/20/0/0").status_code == 404


def test_the_route_serves_the_tilejson(client):
    r = client.get("/collections/rome/tiles/WebMercatorQuad/metadata?f=tilejson")
    assert r.status_code == 200, r.text[:300]
    assert r.json()["vector_layers"][0]["id"] == "rome"


def test_the_route_answers_an_unknown_collection_with_404(client):
    from tests.test_tiles_async_route import _get

    assert _get(client, "/collections/nowhere/tiles/WebMercatorQuad/0/0/0").status_code == 404


# --- martin's errors, by who is at fault -----------------------------------------

SECRET = "s3://private-bucket/credentials-in-path"


@pytest.mark.parametrize(
    ("error", "status"),
    [
        ("TileRequestError", 404),
        ("ValueError", 404),
        # the provider names its own source: martin not knowing it is a server fault
        ("UnknownSourceError", 500),
        ("TileFetchError", 500),
        ("RuntimeError", 500),
    ],
)
def test_the_route_maps_martin_errors_to_status(client, error, status):
    """A request error is a missing tile; a failing source is a 500 that leaks no detail."""
    import builtins

    import martin_py

    from tests.test_tiles_async_route import _get

    raised = getattr(martin_py, error, None) or getattr(builtins, error)

    class FailingTileServer:
        @classmethod
        def from_dict(cls, config, *, worker_threads=None):
            return cls()

        def list_sources(self):
            return ["rome"]

        def get_tile(self, *args, **kwargs):
            raise raised(SECRET)

        async def aget_tile(self, *args, **kwargs):
            raise raised(SECRET)

    with mock.patch.object(martin_py, "TileServer", FailingTileServer):
        r = _get(client, "/collections/rome/tiles/WebMercatorQuad/0/0/0")

    assert r.status_code == status
    assert SECRET not in r.text


def test_the_route_answers_500_for_data_martin_cannot_load(tmp_path):
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
    from tests.test_tiles_async_route import _collection, _config, _get

    config = _config({"gone": _collection("Gone", [_provider_def(tmp_path / "gone.geojson")])})
    client = TestClient(
        build_pygeoapi_subapp(config, build_openapi(config)), raise_server_exceptions=False
    )
    assert _get(client, "/collections/gone/tiles/WebMercatorQuad/0/0/0").status_code == 500


# --- without martin-py --------------------------------------------------------------


def test_without_martin_py_the_module_imports_and_the_provider_refuses_to_build(geojson):
    with mock.patch.dict(sys.modules, {"martin_py": None}):
        sys.modules.pop("app.provider.martin", None)
        module = importlib.import_module("app.provider.martin")
        assert module.martin_py is None
        with pytest.raises(ImportError, match="uv sync --extra martin"):
            module.MartinTilesProvider(_provider_def(geojson))


# --- in the whole app, behind its auth ------------------------------------------------

BASE_ENV = {
    "ENV_STATE": "dev",
    "HOST": "0.0.0.0",
    "PORT": "5000",
    "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
    "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
    "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
    "DEV_FASTGEOAPI_WITH_MCP": "false",
    "DEV_OPA_ENABLED": "false",
    "DEV_API_KEY_ENABLED": "false",
    "DEV_JWKS_ENABLED": "false",
}

LAKES_TILES_PATH = "/geoapi/collections/lakes-tiles/tiles/WebMercatorQuad/0/0/0"


@pytest.fixture
def pygeoapi_config(tmp_path) -> Path:
    """The repo fixture plus `lakes-tiles`: its lakes, cut into tiles by martin."""
    config = yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text())
    lakes = config["resources"]["lakes"]
    config["resources"]["lakes-tiles"] = {
        **{key: value for key, value in lakes.items() if key != "providers"},
        "providers": [_provider_def(lakes["providers"][0]["data"])],
    }
    path = tmp_path / "pygeoapi-config.yml"
    path.write_text(yaml.safe_dump(config))
    return path


def _reload_app():
    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    import app.main as main_mod

    return main_mod.app


def test_the_app_serves_martin_tiles_under_the_collections(pygeoapi_config):
    env = {**BASE_ENV, "DEV_PYGEOAPI_CONFIG": str(pygeoapi_config)}
    with mock.patch.dict(os.environ, env, clear=False):
        app = _reload_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get(LAKES_TILES_PATH, params={"f": "mvt"})
    assert r.status_code == 200
    assert r.headers["content-type"] == MVT
    assert r.content


def test_the_app_requires_the_api_key_for_martin_tiles(pygeoapi_config):
    """The same auth chain as every other collection: no key, no tiles."""
    env = {
        **BASE_ENV,
        "DEV_PYGEOAPI_CONFIG": str(pygeoapi_config),
        "DEV_API_KEY_ENABLED": "true",
        "DEV_PYGEOAPI_KEY_GLOBAL": "pygeoapi",
    }
    # requests stay inside the patch: the key middleware reads the valid
    # keys (PYGEOAPI_KEY_*) from os.environ on every request
    with mock.patch.dict(os.environ, env, clear=False):
        app = _reload_app()
        with TestClient(app, raise_server_exceptions=False) as client:
            anonymous = client.get(LAKES_TILES_PATH, params={"f": "mvt"})
            with_key = client.get(
                LAKES_TILES_PATH, params={"f": "mvt"}, headers={"X-API-KEY": "pygeoapi"}
            )
    assert anonymous.status_code in (401, 403)
    assert with_key.status_code == 200
