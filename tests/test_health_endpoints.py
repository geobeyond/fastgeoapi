"""Health and readiness endpoints (fastgeoapi.cloud P0.a).

Orchestrators (Fly checks, Kubernetes probes, the fastgeoapi-cloud
control plane) need liveness/readiness endpoints that answer OUTSIDE
every authentication chain and OUTSIDE the pygeoapi context path —
until now the only probe available was ``/geoapi/openapi``, which sits
behind whatever auth mode is enabled.

Contract:
- ``GET /healthz`` — liveness: the process is up → 200 as soon as the
  app is serving, in every auth mode, no credentials required.
- ``GET /readyz``  — readiness: the pygeoapi sub-app is mounted and
  its OpenAPI document is available → 200 when ready.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest
from starlette.testclient import TestClient

BASE_ENV = {
    "ENV_STATE": "dev",
    "HOST": "0.0.0.0",
    "PORT": "5000",
    "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
    "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
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


@pytest.fixture
def app_no_auth():
    env = {**BASE_ENV, "DEV_API_KEY_ENABLED": "false", "DEV_JWKS_ENABLED": "false"}
    with mock.patch.dict(os.environ, env, clear=False):
        yield _reload_app(env)


@pytest.fixture
def app_with_api_key():
    env = {
        **BASE_ENV,
        "DEV_API_KEY_ENABLED": "true",
        "DEV_JWKS_ENABLED": "false",
        "DEV_PYGEOAPI_KEY_GLOBAL": "test-api-key",
        "PYGEOAPI_KEY_GLOBAL": "test-api-key",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        yield _reload_app(env)


def test_healthz_returns_200_without_credentials(app_no_auth):
    """Liveness answers 200 with a JSON status body."""
    client = TestClient(app_no_auth, raise_server_exceptions=False)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_returns_200_when_pygeoapi_is_mounted(app_no_auth):
    """Readiness answers 200 once the pygeoapi sub-app is available."""
    client = TestClient(app_no_auth, raise_server_exceptions=False)
    r = client.get("/readyz")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_health_endpoints_bypass_api_key_auth(app_with_api_key):
    """Probes must not require credentials in any auth mode.

    With API key auth enabled the pygeoapi surface returns 401 without
    a key — the probes must keep answering 200 regardless.
    """
    client = TestClient(app_with_api_key, raise_server_exceptions=False)

    # Sanity: the protected surface IS protected.
    assert client.get("/geoapi/").status_code == 401
    # Probes: outside the auth chain.
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200


def test_health_endpoints_not_under_pygeoapi_context(app_no_auth):
    """Probes live at root, not under FASTGEOAPI_CONTEXT."""
    client = TestClient(app_no_auth, raise_server_exceptions=False)
    assert client.get("/geoapi/healthz").status_code in (404, 400)
