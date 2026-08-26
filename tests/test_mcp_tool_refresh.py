"""Regenerating the MCP tool list when the configuration changes.

The tools an MCP client sees are derived from the OpenAPI document. A
reload rebuilds that document, so without this the server keeps
advertising the collections the *previous* configuration exposed and a
machine restart is the only way out — the limitation ADR-0003 declared.

FastMCP 4 asks its providers for the tool list on every `tools/list`
rather than reading a frozen registry, which is the seam these tests
pin down.
"""

from pathlib import Path

import httpx2
import pytest
from fastmcp import FastMCP

from app.mcp.tools import refresh_tools


def _spec(*operations: tuple[str, str]) -> dict:
    """A minimal OpenAPI document exposing one GET per operation."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "test", "version": "1"},
        "paths": {
            path: {"get": {"operationId": op, "responses": {"200": {"description": "ok"}}}}
            for path, op in operations
        },
    }


@pytest.fixture
def client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient(base_url="http://example.invalid")


@pytest.fixture
def server(client) -> FastMCP:
    return FastMCP.from_openapi(
        openapi_spec=_spec(("/lakes", "getLakes")),
        client=client,
        name="test",
    )


@pytest.mark.asyncio
async def test_refreshing_advertises_the_new_collections(server, client):
    """A collection added to the configuration becomes callable."""
    assert sorted(t.name for t in await server.list_tools()) == ["getLakes"]

    refresh_tools(
        server,
        _spec(("/lakes", "getLakes"), ("/lazio-roads", "getLazioRoads")),
        client=client,
    )

    assert sorted(t.name for t in await server.list_tools()) == ["getLakes", "getLazioRoads"]


@pytest.mark.asyncio
async def test_refreshing_drops_the_collections_that_went_away(server, client):
    """A collection removed from the configuration stops being offered.

    Half the point: an operator who takes a dataset out of the
    configuration must not leave a tool behind that still calls it.
    """
    refresh_tools(server, _spec(("/obs", "getObs")), client=client)

    assert sorted(t.name for t in await server.list_tools()) == ["getObs"]


@pytest.mark.asyncio
async def test_the_server_object_survives_the_refresh(server, client):
    """Only the providers are replaced, never the server itself.

    The mounted ASGI app and its stateless session manager belong to the
    server object. Rebuilding it would mean re-entering its lifespan at
    runtime, which is exactly what this approach avoids — so the
    identity of the server must not change.
    """
    before = id(server)

    refresh_tools(server, _spec(("/obs", "getObs")), client=client)

    assert id(server) == before


def test_fastmcp_still_resolves_tools_through_a_mutable_provider_list(server):
    """Drift guard on the FastMCP internal this feature stands on.

    `providers` being a mutable list is an implementation detail of
    FastMCP 4.0.0b3, not a documented contract. If an upgrade changes
    the shape, this goes red — rather than leaving a reload that
    silently stops refreshing anything.
    """
    assert isinstance(server.providers, list), type(server.providers)
    assert server.providers, "a server built from OpenAPI must carry at least one provider"


@pytest.mark.asyncio
async def test_a_reload_regenerates_the_tools_of_the_running_server(tmp_path):
    """End to end: a collection added by a reload becomes an MCP tool.

    This is the limitation ADR-0003 declared, and the reason it existed:
    the tool list was fixed at startup, so a reload left MCP clients
    looking at the previous configuration until the process restarted.

    The app is driven directly rather than through a TestClient: the
    mounted MCP app owns a session manager that does not survive being
    started twice in one test session, and nothing here needs it.
    """
    import copy
    import os
    import sys
    from unittest import mock

    import yaml

    config = yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text())
    target = tmp_path / "pygeoapi-config.yml"
    target.write_text(yaml.safe_dump(config))

    env = {
        "ENV_STATE": "dev",
        "HOST": "0.0.0.0",
        "PORT": "5000",
        "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
        "PYGEOAPI_BASEURL": "http://localhost:5000",
        "DEV_PYGEOAPI_CONFIG": str(target),
        "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
        "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
        "FASTGEOAPI_CONTEXT": "/geoapi",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
    }

    with mock.patch.dict(os.environ, env, clear=False):
        for key in [k for k in sys.modules if k.startswith("app.")]:
            del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        server = main_mod.mcp
        assert server is not None, "the MCP server must be built for this test"
        # Without the middleware pipeline: it expects a live MCP session,
        # and what is under test is the catalogue, not the request path.
        before = {t.name for t in await server.list_tools(run_middleware=False)}
        assert not any("Lakes_bis" in name for name in before), sorted(before)

        changed = copy.deepcopy(config)
        changed["resources"]["lakes-bis"] = copy.deepcopy(config["resources"]["lakes"])
        changed["resources"]["lakes-bis"]["title"] = {"en": "Lakes bis"}
        target.write_text(yaml.safe_dump(changed))

        await main_mod.app.state.reload_manager._run()

        after = {t.name for t in await server.list_tools(run_middleware=False)}

    assert main_mod.app.state.reload_manager.status()["last"]["outcome"] == "applied"
    # pygeoapi coins the operationId from the collection id, and
    # FastMCP builds the tool name from that: `lakes-bis` becomes
    # `Lakes_bis`, so the client gets getLakes_bisFeatures and friends.
    assert any("Lakes_bis" in name for name in after), sorted(after - before)
