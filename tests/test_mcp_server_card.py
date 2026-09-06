"""The server card a deployment publishes for its MCP endpoint (ADR-0009).

SEP-2127 gives clients and install choosers one document to read before
any handshake: where to connect, what the server is called, which
protocol eras it speaks. This suite pins the document's shape and the
naming rule, then the two properties that make it trustworthy: it is
served only when MCP is on, and it follows a configuration reload.
"""

from importlib.metadata import version as package_version

import pytest

from app.mcp.card import (
    SERVER_CARD_PATH,
    SUPPORTED_PROTOCOL_VERSIONS,
    build_server_card,
    default_server_name,
)

# What pygeoapi hands us: `info` already carries title and description
# resolved in the server's default language.
OPENAPI = {
    "openapi": "3.0.0",
    "info": {
        "title": "fastgeoapi demo",
        "description": "Lakes, observations and two Overture collections",
        "version": "0.24.0",
    },
    "paths": {},
}

DEMO = "https://fastgeoapi.fly.dev"


def test_the_card_has_exactly_the_fields_the_sep_defines():
    """Shape pin: these keys, these values, nothing else.

    Adding `icons` or anything optional later is a deliberate act that
    updates this test, not a drift that goes unnoticed.
    """
    card = build_server_card(OPENAPI, base_url=DEMO, context="/geoapi")

    assert card == {
        "$schema": "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json",
        "name": "dev.fly.fastgeoapi/fastgeoapi",
        "version": package_version("fastgeoapi"),
        "title": "fastgeoapi demo",
        "description": "Lakes, observations and two Overture collections",
        "websiteUrl": "https://fastgeoapi.fly.dev/geoapi",
        "repository": {"url": "https://github.com/geobeyond/fastgeoapi", "source": "github"},
        "remotes": [
            {
                "type": "streamable-http",
                "url": "https://fastgeoapi.fly.dev/mcp/",
                "supportedProtocolVersions": ["2026-07-28", "2025-11-25"],
            }
        ],
    }


def test_the_protocol_versions_are_the_two_observed_live():
    """The SDK publishes no list, so this constant is ours to keep honest."""
    assert list(SUPPORTED_PROTOCOL_VERSIONS) == ["2026-07-28", "2025-11-25"]


def test_the_well_known_path_is_the_seps():
    assert SERVER_CARD_PATH == "/.well-known/mcp-server-card"


def test_a_trailing_slash_on_the_base_url_does_not_double_up():
    card = build_server_card(OPENAPI, base_url=DEMO + "/", context="/geoapi")

    assert card["websiteUrl"] == "https://fastgeoapi.fly.dev/geoapi"
    assert card["remotes"][0]["url"] == "https://fastgeoapi.fly.dev/mcp/"


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://fastgeoapi.fly.dev", "dev.fly.fastgeoapi/fastgeoapi"),
        ("https://geo.example.org:8443/", "org.example.geo/fastgeoapi"),
        # Development: an IP address is not a name, so the namespace is
        # `localhost` — the same for a literal localhost.
        ("http://localhost:5000", "localhost/fastgeoapi"),
        ("http://0.0.0.0:5000", "localhost/fastgeoapi"),
        ("http://127.0.0.1:5000", "localhost/fastgeoapi"),
    ],
)
def test_the_default_name_is_the_reversed_host(base_url, expected):
    assert default_server_name(base_url) == expected


def test_an_explicit_name_is_used_as_given():
    card = build_server_card(
        OPENAPI, base_url=DEMO, context="/geoapi", name="it.geobeyond/fastgeoapi"
    )

    assert card["name"] == "it.geobeyond/fastgeoapi"


@pytest.mark.parametrize(
    "name",
    ["fastgeoapi", "it.geobeyond/fastgeoapi/mcp", "/fastgeoapi", "it.geobeyond/"],
)
def test_a_name_that_breaks_the_one_slash_rule_is_refused(name):
    """Better to refuse at startup than to publish a card the Registry rejects."""
    with pytest.raises(ValueError, match="exactly one slash"):
        build_server_card(OPENAPI, base_url=DEMO, context="/geoapi", name=name)


def test_an_explicit_version_wins_over_the_installed_one():
    card = build_server_card(OPENAPI, base_url=DEMO, context="/geoapi", version="9.9.9")

    assert card["version"] == "9.9.9"


def _env(config_path: str, *, with_mcp: bool) -> dict[str, str]:
    """The environment `app.main` needs to build the application in a test.

    Mirrors the reload test in `test_mcp_tool_refresh.py`; unauthenticated
    MCP is opted in explicitly because the fail-closed guard refuses to
    start otherwise.
    """
    return {
        "ENV_STATE": "dev",
        "HOST": "0.0.0.0",
        "PORT": "5000",
        "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
        "PYGEOAPI_BASEURL": "http://localhost:5000",
        # The tracked `.env` sets this too; stating it here keeps the
        # expected URLs below true whatever that file says tomorrow.
        "DEV_APP_URI": "http://localhost:5000",
        "DEV_PYGEOAPI_CONFIG": config_path,
        "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
        "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
        "FASTGEOAPI_CONTEXT": "/geoapi",
        "DEV_FASTGEOAPI_WITH_MCP": "true" if with_mcp else "false",
        "DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED": "true",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
    }


def test_the_card_is_served_at_the_well_known_path_when_mcp_is_on():
    """Public, at the root, with the headers the SEP asks for.

    `Access-Control-Allow-Origin: *` is asserted on a request that sends
    no `Origin`: the app's CORS middleware only answers when one is
    present, and the install chooser fetches the card cross-origin.
    """
    import os
    import sys
    from unittest import mock

    from starlette.testclient import TestClient

    with mock.patch.dict(
        os.environ, _env("tests/data/pygeoapi-config.yml", with_mcp=True), clear=False
    ):
        for key in [k for k in sys.modules if k.startswith("app.")]:
            del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        # No `with`: entering the client runs the lifespan, and the
        # mounted MCP app's session manager does not survive a second
        # start in one test session. A plain route needs none of it.
        response = TestClient(main_mod.app).get(SERVER_CARD_PATH)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-methods"] == "GET"
    assert response.headers["cache-control"] == "public, max-age=3600"
    card = response.json()
    assert card["title"] == "pygeoapi default instance"
    assert card["remotes"][0]["url"] == "http://localhost:5000/mcp/"
    assert card["name"] == "localhost/fastgeoapi"


def test_without_mcp_the_card_does_not_exist():
    """MCP off, route absent: a 404, not an endpoint that says no."""
    import os
    import sys
    from unittest import mock

    from starlette.testclient import TestClient

    with mock.patch.dict(
        os.environ, _env("tests/data/pygeoapi-config.yml", with_mcp=False), clear=False
    ):
        for key in [k for k in sys.modules if k.startswith("app.")]:
            del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        response = TestClient(main_mod.app).get(SERVER_CARD_PATH)

    assert response.status_code == 404


def test_the_name_setting_reaches_the_card():
    """`FASTGEOAPI_MCP_SERVER_NAME` is the operator's namespace, verbatim."""
    import os
    import sys
    from unittest import mock

    from starlette.testclient import TestClient

    env = _env("tests/data/pygeoapi-config.yml", with_mcp=True)
    env["DEV_FASTGEOAPI_MCP_SERVER_NAME"] = "it.geobeyond/fastgeoapi"
    with mock.patch.dict(os.environ, env, clear=False):
        for key in [k for k in sys.modules if k.startswith("app.")]:
            del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        response = TestClient(main_mod.app).get(SERVER_CARD_PATH)

    assert response.json()["name"] == "it.geobeyond/fastgeoapi"


@pytest.mark.asyncio
async def test_a_reload_updates_the_card(tmp_path):
    """Rename the API in the configuration, reload, and the card says so.

    The card is built from the OpenAPI document the tools are generated
    from; both must follow a reload, through the same hook, or an
    operator who renames the API in the editor keeps publishing the old
    name to every install chooser.
    """
    import copy
    import os
    import sys
    from pathlib import Path
    from unittest import mock

    import yaml
    from starlette.testclient import TestClient

    config = yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text())
    target = tmp_path / "pygeoapi-config.yml"
    target.write_text(yaml.safe_dump(config))

    with mock.patch.dict(os.environ, _env(str(target), with_mcp=True), clear=False):
        for key in [k for k in sys.modules if k.startswith("app.")]:
            del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        import app.main as main_mod

        before = TestClient(main_mod.app).get(SERVER_CARD_PATH).json()["title"]
        assert before == "pygeoapi default instance"

        changed = copy.deepcopy(config)
        changed["metadata"]["identification"]["title"] = {
            "en": "Renamed by reload",
            "fr": "Renommé par le rechargement",
        }
        target.write_text(yaml.safe_dump(changed))

        await main_mod.app.state.reload_manager._run()

        after = TestClient(main_mod.app).get(SERVER_CARD_PATH).json()["title"]

    assert main_mod.app.state.reload_manager.status()["last"]["outcome"] == "applied"
    assert after == "Renamed by reload"
