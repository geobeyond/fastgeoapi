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

import logging
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
    "DEV_PYGEOAPI_CONFIG": "tests/data/pygeoapi-config.yml",
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


def test_readyz_reflects_holder_state(app_no_auth):
    """Ready = the programmatic sub-app exists, not 'the openapi file exists'."""
    client = TestClient(app_no_auth, raise_server_exceptions=False)
    holder = app_no_auth.state.pygeoapi_holder
    saved = holder.current
    try:
        holder.current = None
        assert client.get("/readyz").status_code == 503
    finally:
        holder.current = saved
    assert client.get("/readyz").status_code == 200


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


# --- Probe access-log noise -------------------------------------------------
#
# Once the probes are wired into `fly.toml` they fire every 15-30s. On a host
# that keeps only the last ~100 log lines, unfiltered probe access records
# evict everything worth reading — this was diagnosed the hard way while
# chasing an MCP 401 whose evidence had already scrolled out of the buffer.


def _access_record(path: str, status: int = 200) -> logging.LogRecord:
    """Build a record shaped exactly like uvicorn.access emits one."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:0", "GET", path, "1.1", status),
        exc_info=None,
    )


# `_reload_app` purges `app.*` from sys.modules, so a module-level import of
# the filter would go stale and break `isinstance` against the app's own copy.
# Every test below imports it fresh.


@pytest.mark.parametrize("path", ["/healthz", "/readyz", "/readyz?verbose=1"])
def test_probe_access_records_are_dropped(path):
    """Probe requests never reach the log handlers."""
    from app.config.logging import ProbeAccessLogFilter

    assert ProbeAccessLogFilter().filter(_access_record(path)) is False


@pytest.mark.parametrize("path", ["/mcp", "/geoapi/", "/healthzz", "/x/healthz"])
def test_non_probe_access_records_survive(path):
    """Everything else is logged, including near-misses on the probe paths."""
    from app.config.logging import ProbeAccessLogFilter

    assert ProbeAccessLogFilter().filter(_access_record(path)) is True


def test_filter_passes_records_it_does_not_understand():
    """A record that is not a uvicorn access line is left alone."""
    from app.config.logging import ProbeAccessLogFilter

    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="boom",
        args=(),
        exc_info=None,
    )
    assert ProbeAccessLogFilter().filter(record) is True


def test_installing_the_filter_is_idempotent():
    """Repeated startups must not stack duplicate filters."""
    from app.config.logging import ProbeAccessLogFilter, silence_probe_access_logs

    access_logger = logging.getLogger("uvicorn.access")
    original = list(access_logger.filters)
    try:
        access_logger.filters = [f for f in original if not isinstance(f, ProbeAccessLogFilter)]
        silence_probe_access_logs()
        silence_probe_access_logs()
        installed = [f for f in access_logger.filters if isinstance(f, ProbeAccessLogFilter)]
        assert len(installed) == 1
    finally:
        access_logger.filters = original


def test_app_startup_installs_the_filter(app_no_auth):
    """The filter is attached by the lifespan, not merely importable."""
    from app.config.logging import ProbeAccessLogFilter

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.filters = [
        f for f in access_logger.filters if not isinstance(f, ProbeAccessLogFilter)
    ]
    with TestClient(app_no_auth):
        assert any(isinstance(f, ProbeAccessLogFilter) for f in access_logger.filters)
