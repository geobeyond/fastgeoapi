"""The `/martin-wrapper` benchmark endpoint (app/tiles/martin_wrapper.py).

Opt-in and off by default: mounted only when `FASTGEOAPI_MARTIN_WRAPPER_CONFIG`
names a Martin config file AND the optional `martin-py` dependency (the
`martin_wrapper` extra) is installed. Neither condition holds is exercised
without the extra by forcing `martin_py`'s import to fail.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest
import yaml
from starlette.testclient import TestClient

pytest.importorskip("martin_py", reason="the /martin-wrapper tests need the `martin_wrapper` extra")

FIXTURE_GEOJSON = Path(__file__).parent / "data" / "martin_wrapper" / "feature_collection.geojson"


def _write_martin_config(tmp_path: Path, source_id: str = "wrapper_source") -> Path:
    config_path = tmp_path / "martin-config.yaml"
    config_path.write_text(
        yaml.safe_dump({"geojson": {"sources": {source_id: str(FIXTURE_GEOJSON)}}})
    )
    return config_path


# --- app/tiles/martin_wrapper.py directly -----------------------------------


def test_build_martin_wrapper_app_serves_a_tile(tmp_path):
    from app.tiles.martin_wrapper import build_martin_wrapper_app

    config_path = _write_martin_config(tmp_path)
    sub_app = build_martin_wrapper_app(str(config_path))

    with TestClient(sub_app) as client:
        r = client.get("/wrapper_source/0/0/0")

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-protobuf"
    assert len(r.content) > 0
    assert "content-encoding" not in r.headers


def test_build_martin_wrapper_app_unknown_source_is_404(tmp_path):
    from app.tiles.martin_wrapper import build_martin_wrapper_app

    config_path = _write_martin_config(tmp_path)
    sub_app = build_martin_wrapper_app(str(config_path))

    with TestClient(sub_app) as client:
        r = client.get("/does-not-exist/0/0/0")

    assert r.status_code == 404
    assert r.json()["code"] == "NotFound"


def test_build_martin_wrapper_app_rejects_bad_config(tmp_path):
    from app.tiles.martin_wrapper import build_martin_wrapper_app

    with pytest.raises(RuntimeError):
        build_martin_wrapper_app(str(tmp_path / "no-such-config.yaml"))


# --- build_martin_wrapper_app_from_pygeoapi (the "auto" path) ---------------


def test_build_martin_wrapper_app_from_pygeoapi_serves_a_tile():
    from app.tiles.martin_wrapper import build_martin_wrapper_app_from_pygeoapi

    pygeoapi_config = {
        "resources": {
            "lakes": {
                "providers": [{"type": "feature", "name": "GeoJSON", "data": str(FIXTURE_GEOJSON)}]
            }
        }
    }
    sub_app = build_martin_wrapper_app_from_pygeoapi(pygeoapi_config)
    assert sub_app is not None

    with TestClient(sub_app) as client:
        r = client.get("/lakes/0/0/0")

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-protobuf"


def test_build_martin_wrapper_app_from_pygeoapi_returns_none_when_nothing_manageable():
    from app.tiles.martin_wrapper import build_martin_wrapper_app_from_pygeoapi

    pygeoapi_config = {
        "resources": {"obs": {"providers": [{"type": "feature", "name": "CSV", "data": "obs.csv"}]}}
    }
    assert build_martin_wrapper_app_from_pygeoapi(pygeoapi_config) is None


def test_build_martin_wrapper_app_from_pygeoapi_leaves_no_temp_file_behind():
    """The derived config only ever crosses the TileServer(path) call."""
    from app.tiles import martin_wrapper as martin_wrapper_mod

    seen: list[Path] = []
    original_mkstemp = martin_wrapper_mod.tempfile.mkstemp

    def spying_mkstemp(*args, **kwargs):
        fd, path = original_mkstemp(*args, **kwargs)
        seen.append(Path(path))
        return fd, path

    pygeoapi_config = {
        "resources": {
            "lakes": {
                "providers": [{"type": "feature", "name": "GeoJSON", "data": str(FIXTURE_GEOJSON)}]
            }
        }
    }
    with mock.patch.object(martin_wrapper_mod.tempfile, "mkstemp", spying_mkstemp):
        martin_wrapper_mod.build_martin_wrapper_app_from_pygeoapi(pygeoapi_config)

    assert seen and not seen[0].exists()


# --- wired into app.main.create_app() ---------------------------------------

BASE_ENV = {
    "ENV_STATE": "dev",
    "HOST": "0.0.0.0",
    "PORT": "5000",
    "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
    "DEV_PYGEOAPI_CONFIG": "tests/data/pygeoapi-config.yml",
    "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
    "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
    "DEV_FASTGEOAPI_WITH_MCP": "false",
    "DEV_OPA_ENABLED": "false",
    "DEV_API_KEY_ENABLED": "false",
    "DEV_JWKS_ENABLED": "false",
    "DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG": "",
}


def _reload_app(env: dict[str, str]):
    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    import app.main as main_mod

    return main_mod.app


def test_martin_wrapper_not_mounted_without_config():
    """Off by default: no config path, no mount, no import of martin_py."""
    with mock.patch.dict(os.environ, BASE_ENV, clear=False):
        app = _reload_app(BASE_ENV)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/geoapi/martin-wrapper/wrapper_source/0/0/0")
    assert r.status_code == 404


def test_martin_wrapper_mounted_when_configured(tmp_path):
    """Set the config path and it serves real tiles at the documented route."""
    config_path = _write_martin_config(tmp_path)
    env = {**BASE_ENV, "DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG": str(config_path)}
    with mock.patch.dict(os.environ, env, clear=False):
        app = _reload_app(env)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/geoapi/martin-wrapper/wrapper_source/0/0/0")
        outside_context = client.get("/martin-wrapper/wrapper_source/0/0/0")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-protobuf"
    assert outside_context.status_code == 404


def test_martin_wrapper_skips_mount_when_dependency_missing(tmp_path):
    """Configured but the optional dependency isn't installed: warn, don't crash."""
    config_path = _write_martin_config(tmp_path)
    env = {**BASE_ENV, "DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG": str(config_path)}
    with mock.patch.dict(os.environ, env, clear=False):
        with mock.patch.dict(sys.modules, {"martin_py": None}):
            app = _reload_app(env)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/geoapi/martin-wrapper/wrapper_source/0/0/0")
    assert r.status_code == 404


# --- "auto" mode: derived from PYGEOAPI_CONFIG, no second file -------------


def test_martin_wrapper_auto_derives_from_the_pygeoapi_config():
    """`tests/data/pygeoapi-config.yml`'s GeoJSON `lakes` resource, with no
    martin-config.yaml of its own — the resource id becomes the source id.
    """
    env = {**BASE_ENV, "DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG": "auto"}
    with mock.patch.dict(os.environ, env, clear=False):
        app = _reload_app(env)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/geoapi/martin-wrapper/lakes/0/0/0")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/x-protobuf"


def test_martin_wrapper_auto_skips_mount_when_pygeoapi_config_has_nothing_manageable(
    tmp_path,
):
    """Only a CSV resource: `auto` derives an empty config, so no mount."""
    base = yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text())
    del base["resources"]["lakes"]
    config_path = tmp_path / "pygeoapi-config.yml"
    config_path.write_text(yaml.safe_dump(base))

    env = {
        **BASE_ENV,
        "DEV_PYGEOAPI_CONFIG": str(config_path),
        "DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG": "auto",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        app = _reload_app(env)
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/geoapi/martin-wrapper/obs/0/0/0")
    assert r.status_code == 404
