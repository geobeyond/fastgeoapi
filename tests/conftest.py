"""Configuration for tests."""

import os
import sys
from unittest import mock

import pytest
import schemathesis
from httpx import Client
from typer.testing import CliRunner

from app.auth.models import TokenPayload
from app.config.app import configuration as cfg


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
    """Return a new app that is being reloaded with any environment variable has being set."""  # noqa
    yield reload_app


@pytest.fixture
def create_protected_with_apikey_app(create_app):
    """Return a protected app with an API key."""

    def _protected_app():
        with mock.patch.dict(
            os.environ,
            {
                "ENV_STATE": "dev",
                "HOST": "0.0.0.0",  # noqa: S104
                "PORT": "5000",
                "DEV_API_KEY_ENABLED": "true",
                "DEV_PYGEOAPI_KEY_GLOBAL": "pygeoapi",
                "DEV_JWKS_ENABLED": "false",
                "DEV_OPA_ENABLED": "false",
            },
            clear=False,
        ):
            app = create_app()
        return app

    yield _protected_app


@pytest.fixture
def create_app_with_reverse_proxy_enabled(create_app):
    """Return a pygeoapi app behind a reverse proxy."""

    def _reverse_proxy_app():
        with mock.patch.dict(
            os.environ,
            {
                "ENV_STATE": "dev",
                "HOST": "0.0.0.0",  # noqa: S104
                "PORT": "5000",
                "DEV_API_KEY_ENABLED": "false",
                "DEV_JWKS_ENABLED": "false",
                "DEV_OPA_ENABLED": "false",
                "DEV_FASTGEOAPI_REVERSE_PROXY": "true",
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
                "HOST": "0.0.0.0",  # noqa: S104
                "PORT": "5000",
                "DEV_API_KEY_ENABLED": "false",
                "DEV_OAUTH2_JWKS_ENDPOINT": "https://76hxgq.logto.app/oidc/jwks",
                "DEV_OAUTH2_TOKEN_ENDPOINT": "https://76hxgq.logto.app/oidc/token",
                "DEV_JWKS_ENABLED": "true",
                "DEV_OPA_ENABLED": "false",
            },
            clear=False,
        ):
            app = create_app()
        return app

    yield _protected_app


@pytest.fixture
def protected_apikey_schema(create_protected_with_apikey_app):
    """Create a protected API key schema, excluding POST /items and OPTIONS endpoints.

    Excludes POST /collections/{collectionId}/items endpoints due to pygeoapi
    advertising these endpoints with invalid JSON Schema references even when
    transactions are not configured.

    Excludes OPTIONS methods for all endpoints as they are not needed for contract
    testing.

    See test_openapi_contract.py module docstring for detailed explanation.
    """
    app = create_protected_with_apikey_app()
    schema = schemathesis.openapi.from_asgi("/geoapi/openapi?f=json", app=app)
    # Configure generation to only use positive (valid) test cases for speed
    schema.config.generation.mode = schemathesis.GenerationMode.POSITIVE
    # Exclude POST /items endpoints with invalid schema references (/$defs/propertyRef)
    schema = schema.exclude(method="POST", path_regex=r".*/items$")
    # Exclude OPTIONS methods for all endpoints
    schema = schema.exclude(method="OPTIONS")
    return schema


@pytest.fixture
def protected_bearer_schema(create_protected_with_bearer_app):
    """Create a protected bearer token schema, excluding POST /items and OPTIONS.

    Excludes POST /collections/{collectionId}/items endpoints due to pygeoapi
    advertising these endpoints with invalid JSON Schema references even when
    transactions are not configured.

    Excludes OPTIONS methods for all endpoints as they are not needed for contract
    testing.

    See test_openapi_contract.py module docstring for detailed explanation.
    """
    app = create_protected_with_bearer_app()
    schema = schemathesis.openapi.from_asgi("/geoapi/openapi?f=json", app=app)
    # Configure generation to only use positive (valid) test cases for speed
    schema.config.generation.mode = schemathesis.GenerationMode.POSITIVE
    # Exclude POST /items endpoints with invalid schema references (/$defs/propertyRef)
    schema = schema.exclude(method="POST", path_regex=r".*/items$")
    # Exclude OPTIONS methods for all endpoints
    schema = schema.exclude(method="OPTIONS")
    return schema


@pytest.fixture
def reverse_proxy_enabled(create_app_with_reverse_proxy_enabled):
    """Create a protected API key schema."""
    app = create_app_with_reverse_proxy_enabled()

    return app


def get_access_token():
    """Fetch an access token."""
    with Client(
        base_url=cfg.OAUTH2_TOKEN_ENDPOINT,
        timeout=30,
    ) as client:
        response = client.post(
            "/",
            headers={
                "Authorization": "Basic czRyZjIzbnlucmNvdGM4NnhuaWVxOlc2RHJhQWJ1MTZnb29yR0xWSE02WFlSUnI4aWpObUww",  # noqa
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
            raise Exception("Error to fetching an access token")


@pytest.fixture
def access_token():
    """Return the access token."""
    _access_token = get_access_token()
    return _access_token
