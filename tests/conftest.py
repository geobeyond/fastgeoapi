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
    if "app.main" in sys.modules:
        del sys.modules["app.main"]
    if "app.config.app" in sys.modules:
        del sys.modules["app.config.app"]
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
                "API_KEY_ENABLED": "true",
                "PYGEOAPI_KEY_GLOBAL": "pygeoapi",
                "JWKS_ENABLED": "false",
                "OPA_ENABLED": "false",
            },
        ):
            app = create_app()
        return app

    yield _protected_app


@pytest.fixture
def create_protected_with_bearer_app(create_app):
    """Return a protected app with a Bearer Token."""

    def _protected_app():
        with mock.patch.dict(
            os.environ,
            {
                "API_KEY_ENABLED": "false",
                "OAUTH2_JWKS_ENDPOINT": "https://76hxgq.logto.app/oidc/jwks",
                "OAUTH2_TOKEN_ENDPOINT": "https://76hxgq.logto.app/oidc/token",
                "JWKS_ENABLED": "true",
                "OPA_ENABLED": "false",
            },
        ):
            app = create_app()
        return app

    yield _protected_app


@pytest.fixture
def protected_apikey_schema(create_protected_with_apikey_app):
    """Create a protected API key schema."""
    app = create_protected_with_apikey_app()

    return schemathesis.from_asgi("/geoapi/openapi?f=json", app=app)


@pytest.fixture
def protected_bearer_schema(create_protected_with_bearer_app):
    """Create a protected API key schema."""
    app = create_protected_with_bearer_app()

    return schemathesis.from_asgi("/geoapi/openapi?f=json", app=app)


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
