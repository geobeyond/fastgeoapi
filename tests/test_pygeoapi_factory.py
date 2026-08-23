"""Programmatic construction: per ADR-0003, no files nor env vars."""

# The subprocess spawns OUR interpreter with a fixed -c string: nothing
# untrusted crosses the boundary (S404/S603 are about untrusted input).
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="module")
def config_dict() -> dict:
    return yaml.safe_load(Path("pygeoapi-config.yml").read_text())


def test_factory_imports_without_pygeoapi_env():
    """The module must NOT depend on PYGEOAPI_CONFIG/PYGEOAPI_OPENAPI.

    An import of ``pygeoapi.starlette_app`` (even an indirect one)
    would blow up here: that module runs ``get_config()`` at import time.
    """
    code = (
        "import os;"
        "os.environ.pop('PYGEOAPI_CONFIG', None);"
        "os.environ.pop('PYGEOAPI_OPENAPI', None);"
        "import app.pygeoapi.factory"
    )
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_build_openapi_from_dict(config_dict):
    from app.pygeoapi.factory import build_openapi

    doc = build_openapi(config_dict)
    assert "/collections" in doc["paths"]
    # The Bug 3b fix is applied at the source.
    assert doc["components"]["schemas"]["queryables"]["additionalProperties"] is True


def test_build_api_from_dicts(config_dict):
    from app.pygeoapi.factory import build_api, build_openapi

    api = build_api(config_dict, build_openapi(config_dict))
    assert api.config is config_dict
    assert api.locales  # l10n initialized by the upstream constructor


@pytest.fixture(scope="module")
def subapp_client(config_dict):
    from starlette.testclient import TestClient

    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    subapp = build_pygeoapi_subapp(config_dict, build_openapi(config_dict))
    return TestClient(subapp, raise_server_exceptions=False)


def test_landing_page_serves_json(subapp_client):
    r = subapp_client.get("/", headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert "links" in r.json()


def test_collections_lists_configured_resources(subapp_client, config_dict):
    r = subapp_client.get("/collections", headers={"Accept": "application/json"})
    assert r.status_code == 200
    served = {c["id"] for c in r.json()["collections"]}
    assert served == {
        key for key, res in config_dict["resources"].items() if res.get("type") == "collection"
    }


def test_items_query_hits_a_real_provider(subapp_client):
    r = subapp_client.get(
        "/collections/lakes/items?limit=2", headers={"Accept": "application/json"}
    )
    assert r.status_code == 200
    assert len(r.json()["features"]) == 2


def test_conformance_is_the_patched_fastgeoapi_handler(subapp_client):
    """The conformance patch (filter by configured providers) is in the table.

    Observable marker: the fastgeoapi handler includes no EDR classes
    when no EDR provider is configured, while upstream lists them all.
    """
    r = subapp_client.get("/conformance", headers={"Accept": "application/json"})
    assert r.status_code == 200
    classes = r.json()["conformsTo"]
    assert not any("edr" in c for c in classes)


def test_openapi_endpoint_serves_document(subapp_client):
    r = subapp_client.get("/openapi", headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.json()["info"]["title"]


def test_unknown_route_is_404(subapp_client):
    assert subapp_client.get("/definitivamente-non-esiste").status_code == 404
