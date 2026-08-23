"""Drift against upstream must be a red test, not a surprise.

Imports ``pygeoapi.starlette_app`` ONLY here (with a test env: that
module runs ``get_config()`` at import time) and compares (path,
methods) of our table with the upstream ``api_routes``. A route added
by a pygeoapi release makes this test fail — the unlocked nox lane on
main surfaces it on every PyPI release.
"""

import os
from pathlib import Path

import yaml


def _normalized(routes) -> set[tuple[str, tuple[str, ...]]]:
    return {(r.path, tuple(sorted((r.methods or {"GET"}) - {"HEAD"}))) for r in routes}


def _upstream_route_set() -> set[tuple[str, tuple[str, ...]]]:
    os.environ.setdefault("PYGEOAPI_CONFIG", str(Path("pygeoapi-config.yml").resolve()))
    os.environ.setdefault("PYGEOAPI_OPENAPI", str(Path("pygeoapi-openapi.yml").resolve()))
    # The repo config interpolates these env vars (grep '\${' pygeoapi-config.yml):
    # upstream resolves them at import time. Our side below uses plain
    # safe_load on purpose: route building does not depend on the values.
    os.environ.setdefault("PYGEOAPI_BASEURL", "http://localhost:5000")
    os.environ.setdefault("FASTGEOAPI_CONTEXT", "/geoapi")
    os.environ.setdefault("HOST", "0.0.0.0")
    os.environ.setdefault("PORT", "5000")
    from pygeoapi.starlette_app import api_routes

    return _normalized(api_routes)


def _ours_route_set() -> set[tuple[str, tuple[str, ...]]]:
    from app.pygeoapi.factory import build_api, build_openapi, build_routes

    config = yaml.safe_load(Path("pygeoapi-config.yml").read_text())
    routes = build_routes(build_api(config, build_openapi(config)))
    return _normalized(routes)


def test_route_table_matches_upstream():
    missing = _upstream_route_set() - _ours_route_set()
    extra = _ours_route_set() - _upstream_route_set()
    assert not missing, f"upstream routes not served by fastgeoapi: {sorted(missing)}"
    assert not extra, f"fastgeoapi routes absent upstream: {sorted(extra)}"
