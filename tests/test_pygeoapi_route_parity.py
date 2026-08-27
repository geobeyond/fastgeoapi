"""Drift against upstream must be a red test, not a surprise.

Imports ``pygeoapi.starlette_app`` ONLY here (with a test env: that
module runs ``get_config()`` at import time) and compares (path,
methods) of our table with the upstream ``api_routes``. A route added
by a pygeoapi release makes this test fail — the unlocked nox lane on
main surfaces it on every PyPI release.
"""

from pathlib import Path

from pygeoapi.util import yaml_load


def _normalized(routes) -> set[tuple[str, tuple[str, ...]]]:
    return {(r.path, tuple(sorted((r.methods or {"GET"}) - {"HEAD"}))) for r in routes}


def _upstream_route_set(monkeypatch) -> set[tuple[str, tuple[str, ...]]]:
    # Assign, never setdefault: other modules boot the app against tmp
    # configs and export PYGEOAPI_OPENAPI as a side effect, so a
    # setdefault here inherits a path whose tmpdir is already gone and
    # upstream's import-time load_openapi_document() dies on it. The
    # values below are the documents this test means to compare.
    monkeypatch.setenv("PYGEOAPI_CONFIG", str(Path("tests/data/pygeoapi-config.yml").resolve()))
    monkeypatch.setenv("PYGEOAPI_OPENAPI", str(Path("pygeoapi-openapi.yml").resolve()))
    # The repo config interpolates these env vars (grep '\${' pygeoapi-config.yml);
    # upstream resolves them at import time.
    monkeypatch.setenv("PYGEOAPI_BASEURL", "http://localhost:5000")
    monkeypatch.setenv("FASTGEOAPI_CONTEXT", "/geoapi")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "5000")
    from pygeoapi.starlette_app import api_routes

    return _normalized(api_routes)


def _ours_route_set() -> set[tuple[str, tuple[str, ...]]]:
    from app.pygeoapi.factory import build_api, build_openapi, build_routes

    config = yaml_load(Path("tests/data/pygeoapi-config.yml").open())
    routes = build_routes(build_api(config, build_openapi(config)))
    return _normalized(routes)


def test_route_table_matches_upstream(monkeypatch):
    upstream = _upstream_route_set(monkeypatch)
    ours = _ours_route_set()
    missing = upstream - ours
    extra = ours - upstream
    assert not missing, f"upstream routes not served by fastgeoapi: {sorted(missing)}"
    assert not extra, f"fastgeoapi routes absent upstream: {sorted(extra)}"
