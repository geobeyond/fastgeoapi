"""The openapi artifact goes wherever the config drives it (Protocol).

Boot writes it only when missing; a reload with outcome ``applied``
rewrites it (the artifact must follow config changes, or it lies to the
control plane); a write failure is never fatal — the runtime does not
read the artifact back (ADR-0003), so an output must not kill the boot.
"""

import copy
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import yaml
from starlette.testclient import TestClient

BASE_ENV = {
    "ENV_STATE": "dev",
    "HOST": "0.0.0.0",
    "PORT": "5000",
    "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
    "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
    "DEV_FASTGEOAPI_WITH_MCP": "false",
    "DEV_OPA_ENABLED": "false",
    "DEV_API_KEY_ENABLED": "false",
    "DEV_JWKS_ENABLED": "false",
}


def _reload_app(env: dict[str, str]):
    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    import app.main as main_mod

    return main_mod.app


@contextmanager
def _boot(tmp_path, artifact_target: str):
    """Boot the app keeping the env patch alive for the caller's block."""
    base = yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text())
    config_path = tmp_path / "pygeoapi-config.yml"
    config_path.write_text(yaml.safe_dump(base))
    env = {
        **BASE_ENV,
        "DEV_PYGEOAPI_CONFIG": str(config_path),
        "DEV_PYGEOAPI_OPENAPI": artifact_target,
    }
    with mock.patch.dict(os.environ, env, clear=False):
        yield _reload_app(env), config_path, base


def test_artifact_written_to_url_target(tmp_path):
    """``PYGEOAPI_OPENAPI`` accepts a storage-layer URL, like the config."""
    target = tmp_path / "artifacts" / "pygeoapi-openapi.yml"
    target.parent.mkdir()
    with _boot(tmp_path, f"file://{target}") as (app, _, _):
        assert app is not None
        doc = yaml.safe_load(target.read_text())
        assert "/collections" in doc["paths"]


def test_unwritable_artifact_target_is_not_fatal(tmp_path):
    """An output artifact must never kill the boot."""
    target = tmp_path / "does-not-exist" / "nested" / "pygeoapi-openapi.yml"
    with _boot(tmp_path, str(target)) as (app, _, _):
        with TestClient(app, raise_server_exceptions=False) as client:
            assert client.get("/readyz").status_code == 200
        assert not target.exists()


def _wait_outcome(client, expected: set[str], timeout: float = 15.0) -> dict:
    last: dict = {}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        last = client.get("/admin/config/reload").json().get("last") or {}
        if last.get("outcome") in expected:
            return last
        time.sleep(0.1)
    raise AssertionError(f"reload outcome not in {expected} within {timeout}s: {last}")


def test_applied_reload_rewrites_the_artifact(tmp_path):
    target = tmp_path / "pygeoapi-openapi.yml"
    with _boot(tmp_path, str(target)) as (app, config_path, base):
        assert target.exists()  # boot wrote it (was missing)
        assert "lakes-bis" not in target.read_text()

        changed = copy.deepcopy(base)
        changed["resources"]["lakes-bis"] = copy.deepcopy(base["resources"]["lakes"])
        changed["resources"]["lakes-bis"]["title"] = {"en": "Lakes bis"}
        config_path.write_text(yaml.safe_dump(changed))

        with TestClient(app) as client:
            client.post("/admin/config/reload")
            assert _wait_outcome(client, {"applied"})["outcome"] == "applied"
        assert "lakes-bis" in target.read_text()


def test_boot_does_not_clobber_an_existing_artifact(tmp_path):
    target = tmp_path / "pygeoapi-openapi.yml"
    target.write_text("sentinel: true\n")
    with _boot(tmp_path, str(target)):
        assert target.read_text() == "sentinel: true\n"
