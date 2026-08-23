"""The full reload cycle on LocalStore: same code path as the cloud.

``POST /admin/config/reload`` webhook (ADR-0003): 202 right away, work
in the background, idempotence via ETag, broken config → the previous
one keeps serving, security = the same auth chain configured for the API.
"""

import copy
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest
import yaml
from starlette.testclient import TestClient

BASE_ENV = {
    "ENV_STATE": "dev",
    "HOST": "0.0.0.0",
    "PORT": "5000",
    "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
    "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
    "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
    "DEV_FASTGEOAPI_WITH_MCP": "false",
    "DEV_OPA_ENABLED": "false",
}


def _reload_app(env: dict[str, str]):
    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    import app.main as main_mod

    return main_mod.app


def _write_config(path: Path, config: dict) -> None:
    path.write_text(yaml.safe_dump(config))


@pytest.fixture
def app_with_tmp_config(tmp_path):
    """Real app with the config served from a tmp directory via LocalStore."""
    base = yaml.safe_load(Path("pygeoapi-config.yml").read_text())
    target = tmp_path / "pygeoapi-config.yml"
    _write_config(target, base)
    env = {
        **BASE_ENV,
        "DEV_PYGEOAPI_CONFIG": str(target),
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        yield _reload_app(env), target, base


def _wait_outcome(client, expected: set[str], timeout: float = 15.0) -> dict:
    last: dict = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        last = client.get("/admin/config/reload").json().get("last") or {}
        if last.get("outcome") in expected:
            return last
        time.sleep(0.1)
    raise AssertionError(f"reload outcome not in {expected} within {timeout}s: {last}")


def test_post_returns_202_immediately(app_with_tmp_config):
    app, _, _ = app_with_tmp_config
    with TestClient(app) as client:
        r = client.post("/admin/config/reload")
        assert r.status_code == 202
        assert r.json()["status"] in ("started", "already-running")


def test_unchanged_etag_is_a_noop(app_with_tmp_config):
    app, _, _ = app_with_tmp_config
    with TestClient(app) as client:
        client.post("/admin/config/reload")
        assert _wait_outcome(client, {"unchanged"})["outcome"] == "unchanged"


def test_new_collection_appears_after_reload(app_with_tmp_config):
    app, target, base = app_with_tmp_config
    with TestClient(app) as client:
        assert "lakes-bis" not in {
            c["id"] for c in client.get("/geoapi/collections?f=json").json()["collections"]
        }
        changed = copy.deepcopy(base)
        changed["resources"]["lakes-bis"] = copy.deepcopy(base["resources"]["lakes"])
        changed["resources"]["lakes-bis"]["title"] = {"en": "Lakes bis"}
        _write_config(target, changed)
        client.post("/admin/config/reload")
        assert _wait_outcome(client, {"applied"})["outcome"] == "applied"
        assert "lakes-bis" in {
            c["id"] for c in client.get("/geoapi/collections?f=json").json()["collections"]
        }


def test_broken_config_keeps_serving_the_old_one(app_with_tmp_config):
    app, target, _ = app_with_tmp_config
    with TestClient(app) as client:
        target.write_text("resources: [broken")
        client.post("/admin/config/reload")
        last = _wait_outcome(client, {"failed"})
        assert "error" in last
        # The old config still serves.
        assert client.get("/geoapi/collections?f=json").status_code == 200


def test_route_set_follows_reload(app_with_tmp_config):
    """ADR-0005: the mounted spec groups follow config updates.

    Dropping the only process resource must unmount the processes
    routes on the next reload — the route set is an output of the
    reload like the served collections already are.
    """
    app, target, base = app_with_tmp_config
    with TestClient(app) as client:
        assert client.get("/geoapi/processes?f=json").status_code == 200
        without_processes = {
            "resources": {
                name: res for name, res in base["resources"].items() if res.get("type") != "process"
            }
        }
        _write_config(target, {**base, **without_processes})
        client.post("/admin/config/reload")
        assert _wait_outcome(client, {"applied"})["outcome"] == "applied"
        assert client.get("/geoapi/processes?f=json").status_code == 404
        # The feature surface is untouched.
        assert client.get("/geoapi/collections?f=json").status_code == 200


def test_reload_is_protected_by_the_configured_auth(tmp_path):
    """Security according to the configuration: with API key on, /admin requires it."""
    target = tmp_path / "pygeoapi-config.yml"
    target.write_text(Path("pygeoapi-config.yml").read_text())
    env = {
        **BASE_ENV,
        "DEV_PYGEOAPI_CONFIG": str(target),
        "DEV_API_KEY_ENABLED": "true",
        "DEV_JWKS_ENABLED": "false",
        "DEV_PYGEOAPI_KEY_GLOBAL": "test-api-key",
        "PYGEOAPI_KEY_GLOBAL": "test-api-key",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        app = _reload_app(env)
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.post("/admin/config/reload").status_code == 401
            assert (
                client.post(
                    "/admin/config/reload", headers={"X-API-KEY": "test-api-key"}
                ).status_code
                == 202
            )
