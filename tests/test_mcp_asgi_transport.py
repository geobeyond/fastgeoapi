"""Security sentinels for the MCP → pygeoapi ASGI transport.

These tests assert the invariants that replaced the
``X-MCP-Internal-Key`` shared-secret bypass (Phase 4.2 of the
fastmcp 3.x migration):

1. The MCP server's httpx client uses an in-process ASGI transport
   (no loopback HTTP).
2. With ADR-0003 the transport target and the public mount share ONE
   ``PygeoapiHolder`` by design (a reload swap must reach both) — the
   invariant is therefore: whenever an auth mode is configured, the
   BARE holder never appears on the public router; only the
   auth-wrapped chain does. Without auth there is nothing to bypass
   and the sharing is intentional.
3. The public OpenAPI / Swagger description does not mention any
   internal-only path.
4. The httpx client's ``base_url`` uses a non-routable virtual
   hostname so that, even if the client object leaks, requests
   cannot reach an external network.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

import httpx  # drives the app from the tests
import httpx2  # the client production hands to FastMCP
import pytest


@pytest.fixture
def fastgeoapi_with_mcp_enabled():
    """Boot fastgeoapi with MCP enabled, no auth, returning (app, mcp_api_client)."""
    env = {
        "ENV_STATE": "dev",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        # Force a clean reload so module-level `app = ...` is re-evaluated.
        for key in list(sys.modules):
            if key.startswith("app."):
                del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        yield main_mod.app, main_mod.mcp_api_client


# ---------------------------------------------------------------------------
# Sentinel 1: MCP api_client uses ASGITransport, not network.
# ---------------------------------------------------------------------------


def test_mcp_api_client_uses_asgi_transport(fastgeoapi_with_mcp_enabled):
    """The MCP-to-pygeoapi client must use ASGITransport, not a network
    transport.

    Primary sentinel for the Phase 4.2 refactor. The class lives in
    httpx2 since the client moved there for FastMCP 4 — the invariant is
    the in-process transport, not the library it comes from.
    """
    _app, api_client = fastgeoapi_with_mcp_enabled
    assert isinstance(api_client._transport, httpx2.ASGITransport)


def test_mcp_api_client_has_no_internal_key_header(fastgeoapi_with_mcp_enabled):
    """The MCP-to-pygeoapi httpx client must not include the legacy
    X-MCP-Internal-Key header — the secret-based bypass is gone."""
    _app, api_client = fastgeoapi_with_mcp_enabled
    assert "X-MCP-Internal-Key" not in api_client.headers


# ---------------------------------------------------------------------------
# Sentinel 2: the raw sub-app is not on FastGeoAPI.routes.
# ---------------------------------------------------------------------------


@pytest.fixture
def fastgeoapi_with_mcp_and_apikey():
    """Boot fastgeoapi with MCP (unauth by opt-in) and API-key on the public surface."""
    env = {
        "ENV_STATE": "dev",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
        "DEV_API_KEY_ENABLED": "true",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
        "DEV_PYGEOAPI_KEY_GLOBAL": "test-api-key",
        "PYGEOAPI_KEY_GLOBAL": "test-api-key",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        for key in list(sys.modules):
            if key.startswith("app."):
                del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        yield main_mod.app, main_mod.mcp_api_client


def test_bare_holder_never_public_when_auth_is_on(fastgeoapi_with_mcp_and_apikey):
    """With an auth mode configured, the public router must expose only
    the auth-wrapped chain — never the bare holder the MCP transport
    uses (which is the auth-free internal path by design).
    """
    app, api_client = fastgeoapi_with_mcp_and_apikey

    internal_target = api_client._transport.app
    mounted_apps = [getattr(route, "app", None) for route in app.routes]

    assert internal_target not in mounted_apps, (
        "The bare PygeoapiHolder (auth-free internal path) must not be "
        "reachable via the public FastAPI router when auth is configured."
    )


def test_holder_is_shared_by_design_without_auth(fastgeoapi_with_mcp_enabled):
    """Without any auth mode there is nothing to bypass: the public
    mount and the MCP transport intentionally share the ONE holder
    (ADR-0003 — a config reload swap must reach both at once)."""
    app, api_client = fastgeoapi_with_mcp_enabled

    internal_target = api_client._transport.app
    mounted_apps = [getattr(route, "app", None) for route in app.routes]

    assert internal_target in mounted_apps


def test_internal_subapp_path_alias_not_mounted(fastgeoapi_with_mcp_enabled):
    """No route on the FastAPI root uses a path that hints at the
    internal transport (e.g. ``/mcp-internal``)."""
    app, _api_client = fastgeoapi_with_mcp_enabled
    mounted_paths = [getattr(route, "path", "") or "" for route in app.routes]
    assert not any(p.startswith("/mcp-internal") for p in mounted_paths)


# ---------------------------------------------------------------------------
# Sentinel 3: OpenAPI / Swagger does not leak any internal path.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openapi_json_does_not_reference_internal_subapp(
    fastgeoapi_with_mcp_enabled,
):
    """The public ``/openapi.json`` (FastAPI schema) must not contain any
    path that hints at the internal-only sub-app."""
    app, _api_client = fastgeoapi_with_mcp_enabled
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    for path in spec.get("paths", {}):
        assert "mcp-internal" not in path


# ---------------------------------------------------------------------------
# Sentinel 4: base_url uses a virtual, non-routable hostname.
# ---------------------------------------------------------------------------


def test_internal_base_url_uses_virtual_hostname(fastgeoapi_with_mcp_enabled):
    """The MCP api_client must target a non-routable virtual hostname.

    If the client object somehow leaked outside the process, requests
    against it should fail DNS resolution rather than reach a real
    public host. ``http://mcp-internal`` matches that requirement.
    """
    _app, api_client = fastgeoapi_with_mcp_enabled
    base = str(api_client.base_url)
    assert base.startswith("http://mcp-internal"), (
        f"Expected MCP api_client base_url to use the virtual "
        f"'mcp-internal' hostname, got: {base!r}"
    )
