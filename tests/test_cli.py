"""Test cases for the cli module."""

import os
from unittest import mock

from typer.testing import CliRunner

from app.cli import app


def test_openapi_succeeds(runner: CliRunner) -> None:
    """It exits with a status code of zero."""
    env_vars = {
        "ENV_STATE": "dev",
        "HOST": "0.0.0.0",
        "PORT": "5000",
        "DEV_LOG_PATH": "/tmp",
        "DEV_LOG_FILENAME": "fastgeoapi-test.log",
        "DEV_LOG_LEVEL": "debug",
        "DEV_LOG_ENQUEUE": "false",
        "DEV_LOG_ROTATION": "1 days",
        "DEV_LOG_RETENTION": "1 months",
        "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
        "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
        "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
        "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
    }

    with mock.patch.dict(os.environ, env_vars, clear=False):
        result = runner.invoke(app, ["openapi"])
        assert result.exit_code == 0
