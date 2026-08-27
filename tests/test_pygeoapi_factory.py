"""Programmatic construction: per ADR-0003, no files nor env vars."""

# The subprocess spawns OUR interpreter with a fixed -c string: nothing
# untrusted crosses the boundary (S404/S603 are about untrusted input).
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path

import pytest
from pygeoapi.util import yaml_load


@pytest.fixture(scope="module")
def config_dict() -> dict:
    return yaml_load(Path("tests/data/pygeoapi-config.yml").open())


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


def test_served_links_honour_the_configured_base_url(monkeypatch):
    """Link hrefs must carry the configured base URL, placeholders resolved.

    This is the contract a reader notices first: a deployment on port
    5001 whose links all say 5000 is broken even though every route
    answers. The base URL travels from the config through the
    interpolation into pygeoapi's link building, so pin it end to end
    rather than trusting any single hop.
    """
    from starlette.testclient import TestClient

    from app.config.source import load_config_source
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    monkeypatch.setenv("FASTGEOAPI_TEST_BASEURL", "http://links.example:5001")
    monkeypatch.setenv("FASTGEOAPI_TEST_CONTEXT", "/geoapi")
    # The repo config interpolates these too (server.bind).
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "5001")

    source = Path("tests/data/pygeoapi-config.yml")
    config_text = source.read_text().replace(
        "${PYGEOAPI_BASEURL}${FASTGEOAPI_CONTEXT}",
        "${FASTGEOAPI_TEST_BASEURL}${FASTGEOAPI_TEST_CONTEXT}",
    )
    target = Path("/tmp") / "fastgeoapi-links-config.yml"
    target.write_text(config_text)

    config = load_config_source(str(target)).config
    assert config["server"]["url"] == "http://links.example:5001/geoapi"

    client = TestClient(
        build_pygeoapi_subapp(config, build_openapi(config)),
        raise_server_exceptions=False,
    )
    body = client.get("/collections?f=json").json()
    hrefs = [link["href"] for link in body["collections"][0]["links"]]
    served = [href for href in hrefs if href.startswith("http://links.example:5001/geoapi")]
    assert served, f"no link carries the configured base URL: {hrefs}"


def test_missing_limits_get_the_schema_defaults():
    """A config without ``server.limits`` must still be servable.

    pygeoapi's JSON Schema documents ``default_items``/``max_items`` with
    a default of 10 but requires neither, while its HTML template
    dereferences them unconditionally. Filling the documented defaults
    keeps "schema-valid config" and "the server works" the same
    statement — including in a browser.
    """
    from app.pygeoapi.factory import build_api, build_openapi

    config = {
        "server": {
            "bind": {"host": "0.0.0.0", "port": 5000},
            "url": "http://localhost:5000",
            "mimetype": "application/json; charset=UTF-8",
            "encoding": "utf-8",
            "language": "en-US",
            "map": {"url": "https://tile.example/{z}/{x}/{y}.png", "attribution": "x"},
        },
        "logging": {"level": "ERROR"},
        "metadata": {
            "identification": {
                "title": {"en": "t"},
                "description": {"en": "d"},
                "keywords": {"en": ["k"]},
                "keywords_type": "theme",
                "terms_of_service": "https://example.org",
                "url": "https://example.org",
            },
            "license": {"name": "CC-BY 4.0", "url": "https://example.org"},
            "provider": {"name": "geobeyond", "url": "https://geobeyond.it"},
            "contact": {"name": "t", "email": "t@example.org"},
        },
        "resources": {},
    }

    api = build_api(config, build_openapi(config))

    assert api.config["server"]["limits"]["default_items"] == 10
    assert api.config["server"]["limits"]["max_items"] == 10
    # The template reads the deepcopy, so that must carry them too.
    assert api.tpl_config["server"]["limits"]["default_items"] == 10


def test_configured_limits_are_left_alone(config_dict):
    """Only absent keys are filled — a tenant's own limits stay put.

    Given a whole configuration rather than the `server.limits` fragment
    this used to pass: `normalize_config` now validates before filling,
    which is the point of it — it is where a document becomes something
    to build from, and a fragment is not that.
    """
    import copy

    from app.pygeoapi.factory import normalize_config

    config = copy.deepcopy(config_dict)
    config["server"]["limits"] = {"default_items": 25, "max_items": 500}

    normalize_config(config)

    assert config["server"]["limits"] == {"default_items": 25, "max_items": 500}
