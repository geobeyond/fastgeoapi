"""Route registry (ADR-0005): only what the config exposes gets mounted.

OpenAPI and conformance already derive from the config; the route table
was the last static surface. ``active_specs`` closes the triangle, and
the reload webhook recomputes the set on every config update.
"""

from pathlib import Path

import pytest
from pygeoapi.util import yaml_load

from app.pygeoapi.registry import active_specs


def _config_with(resources: dict) -> dict:
    return {"server": {}, "logging": {}, "metadata": {}, "resources": resources}


def _collection(provider_type: str) -> dict:
    return {"type": "collection", "providers": [{"type": provider_type}]}


def test_empty_config_activates_core_only():
    assert active_specs(_config_with({})) == frozenset({"core"})


@pytest.mark.parametrize(
    ("provider_type", "spec"),
    [
        ("feature", "features"),
        ("record", "features"),
        ("tile", "tiles"),
        ("coverage", "coverages"),
        ("map", "maps"),
        ("edr", "edr"),
    ],
)
def test_provider_types_activate_their_spec(provider_type, spec):
    config = _config_with({"x": _collection(provider_type)})
    assert active_specs(config) == frozenset({"core", spec})


def test_process_resources_activate_processes():
    config = _config_with({"hello": {"type": "process", "processor": {"name": "HelloWorld"}}})
    assert active_specs(config) == frozenset({"core", "processes"})


def test_stac_resources_activate_stac():
    config = _config_with({"cat": {"type": "stac-collection"}})
    assert active_specs(config) == frozenset({"core", "stac"})


def test_mixed_resources_accumulate():
    config = _config_with(
        {
            "lakes": _collection("feature"),
            "dem": _collection("coverage"),
            "hello": {"type": "process", "processor": {"name": "HelloWorld"}},
        }
    )
    assert active_specs(config) == frozenset({"core", "features", "coverages", "processes"})


# --- Filtered mounting on the real repo config ------------------------------
#
# The repo config exposes feature collections and one process: tiles, EDR
# and STAC routes must NOT be mounted, while core/features/processes serve.


@pytest.fixture(scope="module")
def repo_subapp_client():
    from starlette.testclient import TestClient

    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    config = yaml_load(Path("tests/data/pygeoapi-config.yml").open())
    subapp = build_pygeoapi_subapp(config, build_openapi(config))
    return TestClient(subapp, raise_server_exceptions=False)


def test_unconfigured_specs_are_not_mounted(repo_subapp_client):
    assert repo_subapp_client.get("/TileMatrixSets").status_code == 404
    assert repo_subapp_client.get("/collections/lakes/position").status_code == 404
    assert repo_subapp_client.get("/stac").status_code == 404


def test_configured_specs_keep_serving(repo_subapp_client):
    assert repo_subapp_client.get("/processes?f=json").status_code == 200
    assert repo_subapp_client.get("/collections/lakes/items?f=json&limit=1").status_code == 200


def test_full_table_stays_available_for_parity():
    """``specs=None`` keeps returning the COMPLETE table: the parity
    contract against upstream is about coverage, not about mounting."""
    from app.pygeoapi.factory import build_api, build_openapi, build_routes
    from app.pygeoapi.registry import active_specs

    config = yaml_load(Path("tests/data/pygeoapi-config.yml").open())
    api = build_api(config, build_openapi(config))
    full = build_routes(api)
    filtered = build_routes(api, specs=active_specs(config))
    assert len(filtered) < len(full)
    assert {r.path for r in filtered} <= {r.path for r in full}
