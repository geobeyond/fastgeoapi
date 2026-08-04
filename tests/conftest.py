"""Configuration for tests."""

import os
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any
from unittest import mock

import httpx
import portpicker
import pytest
import schemathesis
import uvicorn
from httpx import Client
from typer.testing import CliRunner

from app.auth.models import TokenPayload
from app.config.app import configuration as cfg

# Set environment variables at module level for skipif decorators
# These need to be set before test collection happens
os.environ["API_KEY_ENABLED"] = "true"
os.environ["JWKS_ENABLED"] = "true"


@pytest.fixture(scope="session")
def iam_configuration(tmp_path_factory, iam_server_port) -> dict[str, Any]:
    """Override pytest-iam's default config to disable nonce enforcement.

    fastmcp's OIDCProxy doesn't emit ``nonce`` on the upstream
    ``authorization_code`` request (the OIDC spec marks it OPTIONAL when
    ``response_type=code``), but canaille defaults to
    ``REQUIRE_NONCE=True`` which would reject every E2E flow. Real-world
    IdPs we target (Logto, Auth0, Keycloak) don't enforce it for code
    flow, so this override only affects the local test IdP.
    """
    from joserfc.jwk import JWKRegistry

    os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "1"

    jwk = JWKRegistry.generate_key("RSA", 2048)
    jwk.ensure_kid()

    return {
        "TESTING": True,
        "ENV_FILE": None,
        "SECRET_KEY": str(uuid.uuid4()),
        "WTF_CSRF_ENABLED": False,
        "PREFERRED_URL_SCHEME": "http",
        "SERVER_NAME": f"localhost:{iam_server_port}",
        "CANAILLE": {
            "DATABASE": "memory",
            "ENABLE_REGISTRATION": True,
            "JAVASCRIPT": False,
            "ACL": {
                "DEFAULT": {
                    "PERMISSIONS": ["use_oidc", "manage_oidc"],
                }
            },
            "LOGGING": {
                "version": 1,
                "formatters": {
                    "default": {
                        "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
                    }
                },
                "handlers": {
                    "canaille": {
                        "class": "logging.NullHandler",
                        "formatter": "default",
                    }
                },
                "root": {"level": "DEBUG", "handlers": ["canaille"]},
            },
        },
        "CANAILLE_OIDC": {
            "DYNAMIC_CLIENT_REGISTRATION_OPEN": True,
            "ACTIVE_JWKS": [jwk.as_dict()],
            "REQUIRE_NONCE": False,
        },
    }


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()


def reload_app():
    """Reload the app with the test environment variables."""
    # Remove all app modules to ensure clean reload with new environment
    modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
    for module in modules_to_remove:
        del sys.modules[module]

    # Clear the configuration cache
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()

    from app.main import app

    return app


@pytest.fixture
def create_app():
    """Return a new app that is being reloaded with any environment variable has being set."""
    yield reload_app


@pytest.fixture
def create_protected_with_apikey_app(create_app, monkeypatch):
    """Return a protected app with an API key.

    The env vars are set via monkeypatch (restored at fixture teardown,
    i.e. AFTER the test) instead of a `mock.patch.dict` context manager:
    fastapi-key-auth's AuthorizerMiddleware reads the PYGEOAPI_KEY_*
    variables from os.environ at REQUEST time, and the context-manager
    version restored the environment as soon as the app was built —
    wiping the key and turning every request into a 401 for the whole
    test. The contract suite fuzzed the 401 handler for months without
    noticing, until the `not_unauthorized` check exposed it.
    """

    def _protected_app():
        for key, value in {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "API_KEY_ENABLED": "true",
            "DEV_API_KEY_ENABLED": "true",
            "DEV_PYGEOAPI_KEY_GLOBAL": "pygeoapi",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
            # Disable MCP to avoid StreamableHTTPSessionManager reuse issues
            "DEV_FASTGEOAPI_WITH_MCP": "false",
        }.items():
            monkeypatch.setenv(key, value)
        return create_app()

    yield _protected_app


@pytest.fixture
def create_app_with_reverse_proxy_enabled(create_app):
    """Return a pygeoapi app behind a reverse proxy."""

    def _reverse_proxy_app():
        with mock.patch.dict(
            os.environ,
            {
                "ENV_STATE": "dev",
                "HOST": "0.0.0.0",
                "PORT": "5000",
                "DEV_API_KEY_ENABLED": "false",
                "DEV_JWKS_ENABLED": "false",
                "DEV_OPA_ENABLED": "false",
                "DEV_FASTGEOAPI_REVERSE_PROXY": "true",
                # Disable MCP to avoid StreamableHTTPSessionManager reuse issues
                "DEV_FASTGEOAPI_WITH_MCP": "false",
            },
            clear=False,
        ):
            app = create_app()
        return app

    yield _reverse_proxy_app


@pytest.fixture
def create_protected_with_bearer_app(create_app):
    """Return a protected app with a Bearer Token."""

    def _protected_app():
        with mock.patch.dict(
            os.environ,
            {
                "ENV_STATE": "dev",
                "HOST": "0.0.0.0",
                "PORT": "5000",
                "JWKS_ENABLED": "true",
                "DEV_API_KEY_ENABLED": "false",
                "DEV_OAUTH2_JWKS_ENDPOINT": "https://76hxgq.logto.app/oidc/jwks",
                "DEV_OAUTH2_TOKEN_ENDPOINT": "https://76hxgq.logto.app/oidc/token",
                "DEV_JWKS_ENABLED": "true",
                "DEV_OPA_ENABLED": "false",
                # Disable MCP to avoid StreamableHTTPSessionManager reuse issues
                "DEV_FASTGEOAPI_WITH_MCP": "false",
            },
            clear=False,
        ):
            app = create_app()
        return app

    yield _protected_app


@pytest.fixture
def protected_apikey_app(create_protected_with_apikey_app):
    """Return the protected API key app instance."""
    return create_protected_with_apikey_app()


@pytest.fixture
def protected_apikey_schema(create_protected_with_apikey_app):
    """Create a protected API key schema.

    Note: In schemathesis 4.x, filters must be applied on the LazySchema
    returned by from_fixture(), not on the schema in the fixture.
    See test_openapi_contract.py for filter configuration.
    """
    app = create_protected_with_apikey_app()
    return schemathesis.openapi.from_asgi("/geoapi/openapi?f=json", app=app)


@pytest.fixture
def protected_bearer_app(create_protected_with_bearer_app):
    """Return the protected bearer token app instance."""
    return create_protected_with_bearer_app()


@pytest.fixture
def protected_bearer_schema(create_protected_with_bearer_app):
    """Create a protected bearer token schema.

    Note: In schemathesis 4.x, filters must be applied on the LazySchema
    returned by from_fixture(), not on the schema in the fixture.
    See test_openapi_contract.py for filter configuration.
    """
    app = create_protected_with_bearer_app()
    schema = schemathesis.openapi.from_asgi("/geoapi/openapi?f=json", app=app)

    # Schema-level dynamic auth (schemathesis 4.24+): the token endpoint
    # lives on an external IdP, so the config-based `auth.dynamic` (which
    # fetches from a path on the app under test) does not apply — a
    # Python provider does. Schemathesis caches the token between
    # examples (default 300s) and, on a 401, refetches it and replays
    # the request once before failing.
    @schema.auth(retry_on=[401])
    class OAuth2ClientCredentialsProvider:
        """Fetch an access token via client_credentials against the IdP."""

        def get(self, case, context):
            """Return a fresh access token (skips the test if IdP is down)."""
            return get_access_token()

        def set(self, case, data, context):
            """Attach the token as a bearer Authorization header."""
            case.headers["Authorization"] = f"Bearer {data}"

    return schema


@pytest.fixture
def reverse_proxy_enabled(create_app_with_reverse_proxy_enabled):
    """Create a protected API key schema."""
    app = create_app_with_reverse_proxy_enabled()

    return app


@pytest.fixture
def create_unprotected_app(create_app):
    """Return an unprotected app (no authentication)."""

    def _unprotected_app():
        with mock.patch.dict(
            os.environ,
            {
                "ENV_STATE": "dev",
                "HOST": "0.0.0.0",
                "PORT": "5000",
                "DEV_API_KEY_ENABLED": "false",
                "DEV_JWKS_ENABLED": "false",
                "DEV_OPA_ENABLED": "false",
                "DEV_FASTGEOAPI_WITH_MCP": "false",
            },
            clear=False,
        ):
            app = create_app()
        return app

    yield _unprotected_app


@pytest.fixture
def unprotected_app(create_unprotected_app):
    """Return the unprotected app instance."""
    return create_unprotected_app()


def get_access_token():
    """Fetch an access token."""
    try:
        with Client(
            base_url=cfg.OAUTH2_TOKEN_ENDPOINT,
            timeout=30,
        ) as client:
            response = client.post(
                "/",
                headers={
                    "Authorization": "Basic czRyZjIzbnlucmNvdGM4NnhuaWVxOlc2RHJhQWJ1MTZnb29yR0xWSE02WFlSUnI4aWpObUww",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data=TokenPayload(
                    grant_type="client_credentials",
                    resource="http://localhost:5000/geoapi/",
                    scope="openid profile ci",
                ).model_dump(),
            )
            if response.status_code == 200:
                access_token = response.json()["access_token"]
                return access_token
            else:
                pytest.skip("Unable to fetch access token - OAuth2 endpoint not available")
    except Exception:
        pytest.skip("Unable to fetch access token - OAuth2 endpoint not available")


@pytest.fixture
def access_token():
    """Return the access token."""
    _access_token = get_access_token()
    if _access_token is None:
        pytest.skip("Access token not available")
    return _access_token


# ---------------------------------------------------------------------------
# Live-instance fixtures for end-to-end OAuth/MCP tests
#
# Shared by tests/test_mcp_oauth_e2e.py (which asserts each OAuth hop) and
# tests/test_mcp_client_e2e.py (which drives a real MCP client through the
# same flow). They boot a canaille IdP (pytest-iam) plus fastgeoapi under
# uvicorn, both in background threads.
# ---------------------------------------------------------------------------

@pytest.fixture
def fastgeoapi_port() -> int:
    """Pre-pick a free port so the OAuth client and the fastgeoapi instance
    can be configured with the same redirect URI before either is started.
    """
    return portpicker.pick_unused_port()


@pytest.fixture
def iam_oauth_client(iam_server, fastgeoapi_port: int):
    """Register an OAuth client in canaille that mirrors the redirect URI
    of the in-process fastgeoapi MCP server.

    The MCP server's upstream callback is ``<APP_URI>/mcp/auth/callback``.
    The ``iam_server`` fixture is session-scoped, so previously-registered
    clients from earlier tests persist in its in-memory backend — we
    delete any leftover before saving to keep client_id unique and the
    redirect_uri current for this run's port.
    """
    redirect_uri = f"http://localhost:{fastgeoapi_port}/mcp/auth/callback"
    with iam_server.app.app_context():
        existing = iam_server.backend.query(iam_server.models.Client, client_id="mcp-test-client")
        for stale in existing:
            iam_server.backend.delete(stale)
        # canaille stores ``scope`` as ``list[str]``; passing a string here
        # would break the set-based consent check in is_consent_needed().
        client = iam_server.models.Client(
            client_id="mcp-test-client",
            client_secret="test-secret-do-not-use-in-prod",
            client_name="MCP Test Client",
            redirect_uris=[redirect_uri],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope=["openid", "profile", "email"],
            client_id_issued_at=int(time.time()),
            client_secret_expires_at=0,
            # fastmcp's OIDCProxy sends upstream client creds via HTTP Basic.
            token_endpoint_auth_method="client_secret_basic",
        )
        iam_server.backend.save(client)
    try:
        yield client
    finally:
        with iam_server.app.app_context():
            for stale in iam_server.backend.query(
                iam_server.models.Client, client_id="mcp-test-client"
            ):
                iam_server.backend.delete(stale)


@pytest.fixture
def fastgeoapi_with_iam(
    iam_server,
    iam_oauth_client,
    fastgeoapi_port: int,
) -> Iterator[str]:
    """Boot fastgeoapi in a uvicorn thread, configured against the local IdP.

    Yields the base URL of the running instance.
    """
    iam_url = iam_server.url.rstrip("/")
    well_known = f"{iam_url}/.well-known/openid-configuration"

    env = {
        "ENV_STATE": "dev",
        "HOST": "localhost",
        "PORT": str(fastgeoapi_port),
        "DEV_APP_URI": f"http://localhost:{fastgeoapi_port}",
        "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
        "DEV_FASTGEOAPI_WITH_MCP": "true",
        # Pin the consent mode: the full-dance test walks the fastmcp
        # consent interstitial (CSRF double-submit included), so it must
        # not inherit whatever deployment default the repo `.env` carries
        # (lowered to "never" for the single-tenant fly deploy).
        "DEV_FASTGEOAPI_MCP_CONSENT_MODE": "remember",
        "DEV_FASTGEOAPI_REVERSE_PROXY": "false",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "true",
        "DEV_OPA_ENABLED": "false",
        "DEV_OIDC_WELL_KNOWN_ENDPOINT": well_known,
        "DEV_OIDC_CLIENT_ID": iam_oauth_client.client_id,
        "DEV_OIDC_CLIENT_SECRET": iam_oauth_client.client_secret,
        "DEV_OAUTH2_JWKS_ENDPOINT": f"{iam_url}/oauth/jwks.json",
        "DEV_OAUTH2_TOKEN_ENDPOINT": f"{iam_url}/oauth/token",
        "DEV_OAUTH2_EXPECTED_AUDIENCE": f"http://localhost:{fastgeoapi_port}/geoapi/",
        "DEV_OAUTH2_EXPECTED_ISSUER": iam_url,
        "DEV_PYGEOAPI_BASEURL": f"http://localhost:{fastgeoapi_port}",
        "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
        "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
    }

    with mock.patch.dict(os.environ, env, clear=False):
        # Force a fresh import so module-level `app = ...` is re-evaluated
        # under the patched env.
        for key in list(sys.modules):
            if key.startswith("app."):
                del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()

        from app.main import app

        config = uvicorn.Config(
            app,
            host="localhost",
            port=fastgeoapi_port,
            log_level="warning",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        base_url = f"http://localhost:{fastgeoapi_port}"
        # Wait for the server to be ready
        for _ in range(40):
            try:
                r = httpx.get(f"{base_url}/.well-known/oauth-authorization-server/mcp", timeout=1.0)
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.25)
        else:
            server.should_exit = True
            thread.join(timeout=5)
            pytest.fail(f"fastgeoapi did not become ready on {base_url}")

        try:
            yield base_url
        finally:
            server.should_exit = True
            thread.join(timeout=5)
