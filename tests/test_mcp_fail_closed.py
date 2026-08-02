"""Fail-closed sentinels for the MCP authentication guard.

Without the guard, ``create_mcp_server`` silently boots with
``auth=None`` whenever ``JWKS_ENABLED``/``OIDC_WELL_KNOWN_ENDPOINT``
are missing: a single typo'd env var in production exposes every MCP
tool unauthenticated — and since the MCP→pygeoapi hop targets the raw
sub-app (no middleware), the whole API leaks through MCP even when
``/geoapi`` itself is protected.

These tests pin the fail-closed behavior: MCP without auth must refuse
to start, unless the operator opts in explicitly with
``FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED=true`` (the first-class
"passthrough mode" required by the fastgeoapi.cloud track).
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import pytest
from starlette.testclient import TestClient

BASE_ENV = {
    "ENV_STATE": "dev",
    "DEV_FASTGEOAPI_WITH_MCP": "true",
    "DEV_API_KEY_ENABLED": "false",
    "DEV_OPA_ENABLED": "false",
}

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _reload_app_main(extra_env: dict[str, str]):
    """Reload ``app.main`` under the given environment."""
    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    import app.main as main_mod

    return main_mod


def _boot(extra_env: dict[str, str]):
    env = {**BASE_ENV, **extra_env}
    with mock.patch.dict(os.environ, env, clear=False):
        return _reload_app_main(env)


def test_mcp_without_auth_refuses_to_start():
    """MCP enabled + no auth config + no opt-in → refuse to start.

    Note: matched via ``RuntimeError`` (MCPAuthMisconfiguredError's stable
    base) because the module reload recreates the exception class with
    a different identity than any pre-imported reference.
    """
    env = {
        **BASE_ENV,
        "DEV_JWKS_ENABLED": "false",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        with pytest.raises(RuntimeError, match="unauthenticated") as exc:
            _reload_app_main(env)
    assert type(exc.value).__name__ == "MCPAuthMisconfiguredError"


def test_mcp_with_partial_auth_config_refuses_to_start():
    """The production-typo case: JWKS on but the OIDC endpoint missing.

    This is exactly the misconfiguration the guard exists for — before
    the guard it silently booted every MCP tool without authentication.
    """
    env = {
        **BASE_ENV,
        "DEV_JWKS_ENABLED": "true",
        "DEV_OIDC_WELL_KNOWN_ENDPOINT": "",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        with pytest.raises(RuntimeError, match="unauthenticated") as exc:
            _reload_app_main(env)
    assert type(exc.value).__name__ == "MCPAuthMisconfiguredError"


def test_mcp_unauthenticated_optin_boots_and_serves():
    """Explicit opt-in keeps the documented no-auth flow working.

    ``FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED=true`` is the first-class
    passthrough mode: the server boots and MCP answers sessionless
    requests exactly as before.
    """
    main_mod = _boot(
        {
            "DEV_JWKS_ENABLED": "false",
            "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
        }
    )

    with TestClient(main_mod.app, raise_server_exceptions=False) as client:
        r = client.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers=MCP_HEADERS,
        )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
    assert '"tools"' in r.text
