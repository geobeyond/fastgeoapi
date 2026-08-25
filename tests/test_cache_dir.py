"""Cache directory resolution (fastgeoapi.cloud P0.a — cwd-independence).

The external-refs schema cache defaulted to ``Path.cwd()/.cache`` — a
hardcoded cwd dependency that breaks containerized/SaaS layouts where
the working directory is not writable or not stable. The cache root is
now overridable via ``FASTGEOAPI_CACHE_DIR``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

BASE_ENV = {
    "ENV_STATE": "dev",
    "HOST": "0.0.0.0",
    "PORT": "5000",
    "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
    "DEV_PYGEOAPI_CONFIG": "tests/data/pygeoapi-config.yml",
    "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
    "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
    "DEV_FASTGEOAPI_WITH_MCP": "false",
    "DEV_API_KEY_ENABLED": "false",
    "DEV_JWKS_ENABLED": "false",
    "DEV_OPA_ENABLED": "false",
}


def _reload_main(env: dict[str, str]):
    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    import app.main as main_mod

    return main_mod


def test_cache_dir_defaults_to_cwd_dot_cache():
    """Unset env keeps the historical default (cwd/.cache/openapi_refs)."""
    env = {**BASE_ENV, "DEV_FASTGEOAPI_CACHE_DIR": ""}
    with mock.patch.dict(os.environ, env, clear=False):
        main_mod = _reload_main(env)
        assert main_mod._openapi_cache_dir() == Path.cwd() / ".cache" / "openapi_refs"


def test_cache_dir_respects_env_override(tmp_path):
    """FASTGEOAPI_CACHE_DIR relocates the cache root entirely."""
    env = {**BASE_ENV, "DEV_FASTGEOAPI_CACHE_DIR": str(tmp_path / "custom")}
    with mock.patch.dict(os.environ, env, clear=False):
        main_mod = _reload_main(env)
        assert main_mod._openapi_cache_dir() == tmp_path / "custom" / "openapi_refs"
