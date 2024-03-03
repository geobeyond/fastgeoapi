import os
import pytest
import schemathesis
import sys
from typer.testing import CliRunner
from unittest import mock


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()

def reload_app():
    if "app.main" in sys.modules:
        del sys.modules["app.main"]
    if "app.config.app" in sys.modules:
        del sys.modules["app.config.app"]
    from app.main import app

    return app

@pytest.fixture
def create_app():
    """Return a new app that is being reloaded with
    any environment variable has being set"""

    yield reload_app

@pytest.fixture
def create_protected_with_apikey_app(create_app):
    def _protected_app():
        with mock.patch.dict(
            os.environ,
            {
                "API_KEY_ENABLED": "true",
                "PYGEOAPI_KEY_GLOBAL": "pygeoapi",
                "JWKS_ENABLED": "false",
                "OPA_ENABLED": "false"
            }
        ):
            app = create_app()
        return app

    yield _protected_app

@pytest.fixture
def protected_apikey_schema(create_protected_with_apikey_app):
    app = create_protected_with_apikey_app()

    return schemathesis.from_asgi("/geoapi/openapi?f=json", app=app)
