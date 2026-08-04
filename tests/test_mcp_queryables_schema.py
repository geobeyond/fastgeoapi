"""Regression: queryables/schema MCP tools must return the JSON Schema doc.

Bug 3b (vault: "Bug 3 — 401 su schema e queryables (catena
diagnostica)", addendum 2026-08-04): pygeoapi's generated OpenAPI
declares ``components.schemas.queryables`` as a wrapper object with a
required ``queryables`` property (``pygeoapi/openapi.py:440-451``,
still present in 0.24), while the actual handler response — for BOTH
``/queryables`` (Features Part 3) and ``/schema`` (which reuses the
same response component) — is a bare JSON Schema document. fastmcp
validates the legitimate 200 against the wrong wrapper and every
``*Queryables``/``*Schema`` tool dies with ``Output validation error:
'queryables' is a required property``.

Fixed by rewriting the schema in the document fed to fastmcp
(``app/pygeoapi/openapi.py``, mirror of the upstream module that owns
the defect). To be reported upstream to geopython/pygeoapi.
"""

from __future__ import annotations

import json
import os
import sys
from unittest import mock

import pytest


@pytest.fixture
def mcp_main():
    """Boot fastgeoapi with MCP enabled and no auth; yield app.main."""
    env = {
        "ENV_STATE": "dev",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        for key in list(sys.modules):
            if key.startswith("app."):
                del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        yield main_mod


def _payload(res):
    """Unwrap the tool payload from a fastmcp tool result."""
    structured = res.structured_content
    if structured:
        return structured.get("result", structured)
    return json.loads(res.content[0].text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool",
    [
        "getLakesQueryables",
        "getObsQueryables",
        "getLakesSchema",
        "getObsSchema",
    ],
)
async def test_queryables_and_schema_tools_return_json_schema_doc(mcp_main, tool):
    """The four introspection tools must surface pygeoapi's JSON Schema doc.

    The raw sub-app answers 200 with a JSON Schema document
    (``$schema``, ``type``, ``properties`` …): the MCP tool must return
    it instead of failing output validation against pygeoapi's wrong
    wrapper schema.
    """
    from fastmcp import Client

    async with Client(mcp_main.mcp) as client:
        res = await client.call_tool(tool, {})

    doc = _payload(res)
    assert doc.get("type") == "object", doc
    assert "properties" in doc, doc
    # the defining trait of the OGC queryables/schema response
    assert "$schema" in doc or "$id" in doc, doc


def test_served_openapi_declares_truthful_queryables_schema(
    create_protected_with_apikey_app,
):
    """The spec served through OpenapiSecurityMiddleware is honest too.

    ``augment_security`` rebuilds the served document to inject
    securitySchemes: the same pass must also correct pygeoapi's
    queryables wrapper (Bug 3b), so HTTP consumers reading
    ``/geoapi/openapi`` get the same truthful schema fastmcp gets.
    """
    from starlette.testclient import TestClient

    app = create_protected_with_apikey_app()
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/geoapi/openapi", params={"f": "json"})
    assert response.status_code == 200, response.text[:200]
    doc = response.json()

    queryables = doc["components"]["schemas"]["queryables"]
    assert "required" not in queryables, queryables
    assert "$schema" in queryables.get("properties", {}), queryables
    # the security augmentation must keep working alongside the fix
    assert "securitySchemes" in doc["components"], list(doc["components"])


def test_generated_openapi_file_has_truthful_queryables(mcp_main):
    """The standard generation path writes an already-corrected file.

    ``ensure_openapi_file_exists`` generates through the mirror module's
    ``generate_openapi_document`` (upstream + fastgeoapi corrections):
    every consumer of the file — pygeoapi's /openapi endpoint, the MCP
    tool generation — inherits the fix at the source.
    """
    from pathlib import Path

    import yaml

    from app.config.app import configuration as cfg

    doc = yaml.safe_load((Path.cwd() / cfg.PYGEOAPI_OPENAPI).read_text())
    queryables = doc["components"]["schemas"]["queryables"]
    assert "required" not in queryables, queryables
    assert "$schema" in queryables.get("properties", {}), queryables
