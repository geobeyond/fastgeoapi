"""12-factor config defaults (fastgeoapi.cloud P0.a).

A container image must boot from environment variables alone, with no
`.env` file baked in. Logging configuration used to have no defaults,
so a bare container crashed at import time with a TypeError deep in
`create_logger` (Path(None)). These tests pin sensible defaults.
"""

from __future__ import annotations

import os
import sys
from unittest import mock

MINIMAL_ENV = {
    "ENV_STATE": "dev",
    "HOST": "0.0.0.0",
    "PORT": "5000",
    "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
    "DEV_PYGEOAPI_CONFIG": "tests/data/pygeoapi-config.yml",
    "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
    "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
    "DEV_API_KEY_ENABLED": "false",
    "DEV_JWKS_ENABLED": "false",
    "DEV_OPA_ENABLED": "false",
    "DEV_FASTGEOAPI_WITH_MCP": "false",
    # Deliberately NOT set: DEV_LOG_PATH, DEV_LOG_FILENAME
    # Prod equivalents (the same model is validated for both prefixes)
    "PROD_PYGEOAPI_BASEURL": "http://localhost:5000",
    "PROD_PYGEOAPI_CONFIG": "tests/data/pygeoapi-config.yml",
    "PROD_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
    "PROD_FASTGEOAPI_CONTEXT": "/geoapi",
}


def _fresh_config(env: dict[str, str]):
    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    from app.config.app import configuration

    return configuration


def test_logging_has_usable_defaults_without_env_file():
    """LOG_PATH/LOG_FILENAME must be usable without any .env.

    Instantiated with ``_env_file=None`` to exercise the model defaults
    the way a container does: environment only, no dotenv on disk.
    """
    from pathlib import Path

    from app.config.app import DevConfig, ProdConfig

    with mock.patch.dict(os.environ, MINIMAL_ENV, clear=False):
        for var in ("DEV_LOG_PATH", "DEV_LOG_FILENAME", "PROD_LOG_PATH", "PROD_LOG_FILENAME"):
            os.environ.pop(var, None)

        for model in (DevConfig, ProdConfig):
            cfg = model(_env_file=None)
            # Every field create_logger feeds to loguru must be set:
            # a None here crashes the app at import time in a container.
            for field in (
                "LOG_PATH",
                "LOG_FILENAME",
                "LOG_LEVEL",
                "LOG_ROTATION",
                "LOG_RETENTION",
                "LOG_FORMAT",
            ):
                assert getattr(cfg, field) is not None, (
                    f"{model.__name__}.{field} must have a 12-factor default"
                )
            assert isinstance(cfg.LOG_ENQUEUE, bool)
            assert Path(cfg.LOG_PATH) / cfg.LOG_FILENAME
