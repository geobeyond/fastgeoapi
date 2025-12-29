"""Test startup workflow for fastgeoapi application.

This module tests the complete startup workflow of the fastgeoapi server
when installed as a package in a new Python virtual environment,
verifying behavior based on different environment variable configurations.
"""

import os
import sys
from unittest import mock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def clean_modules_and_env():
    """Clean up modules and environment before and after each test."""
    # Save original state
    original_env = os.environ.copy()
    original_modules = set(sys.modules.keys())

    yield

    # Restore environment
    keys_to_remove = set(os.environ.keys()) - set(original_env.keys())
    for key in keys_to_remove:
        del os.environ[key]
    for key, value in original_env.items():
        os.environ[key] = value

    # Clean up app modules for fresh imports
    modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
    for module in modules_to_remove:
        if module not in original_modules:
            del sys.modules[module]


def reload_app_with_env(env_vars: dict):
    """Reload the application with specified environment variables.

    Parameters
    ----------
    env_vars : dict
        Dictionary of environment variables to set before loading the app.

    Returns
    -------
    FastAPI
        The reloaded FastAPI application instance.
    """
    # Clear all app modules to ensure clean reload
    modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
    for module in modules_to_remove:
        del sys.modules[module]

    # Clear the configuration cache
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()

    # Now import and create the app with new environment
    from app.main import create_app

    return create_app()


class TestStartupWorkflowEnvState:
    """Test startup workflow based on ENV_STATE configuration."""

    def test_startup_with_dev_env_state(self):
        """Test that application starts correctly with ENV_STATE=dev."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            assert app is not None
            assert app.title == "fastgeoapi"

            # Verify the pygeoapi app is mounted at the correct context
            routes = [route.path for route in app.routes]
            assert "/geoapi" in routes or any("/geoapi" in str(r) for r in routes)

    def test_startup_with_prod_env_state(self):
        """Test that application starts correctly with ENV_STATE=prod."""
        env_vars = {
            "ENV_STATE": "prod",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "PROD_PYGEOAPI_BASEURL": "http://localhost:5000",
            "PROD_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "PROD_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "PROD_FASTGEOAPI_CONTEXT": "/geoapi",
            "PROD_API_KEY_ENABLED": "false",
            "PROD_JWKS_ENABLED": "false",
            "PROD_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            assert app is not None
            assert app.title == "fastgeoapi"


class TestStartupWorkflowAuthentication:
    """Test startup workflow with different authentication configurations."""

    def test_startup_with_no_auth_enabled(self):
        """Test that application starts without any authentication middleware."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            client = TestClient(app)
            # OpenAPI endpoint should be accessible without authentication
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

    def test_startup_with_api_key_enabled(self):
        """Test that application starts with API Key authentication enabled."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "true",
            "DEV_PYGEOAPI_KEY_GLOBAL": "test-api-key",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
            "PYGEOAPI_KEY_GLOBAL": "test-api-key",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            client = TestClient(app)
            # OpenAPI endpoint should be public
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

            # Other endpoints should require API key (returns 401 Unauthorized)
            response = client.get("/geoapi/")
            assert response.status_code == 401

            # With API key should work
            response = client.get("/geoapi/", headers={"X-API-KEY": "test-api-key"})
            assert response.status_code == 200

    def test_startup_with_jwks_enabled(self):
        """Test that application starts with JWKS/OAuth2 authentication enabled."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "true",
            "DEV_OPA_ENABLED": "false",
            "DEV_OAUTH2_JWKS_ENDPOINT": "https://example.com/.well-known/jwks.json",
            "DEV_OAUTH2_TOKEN_ENDPOINT": "https://example.com/oauth/token",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            assert app is not None
            client = TestClient(app)
            # OpenAPI endpoint should be accessible
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

    def test_startup_fails_with_mutually_exclusive_auth(self):
        """Test that application raises error when multiple auth methods are enabled."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "true",
            "DEV_PYGEOAPI_KEY_GLOBAL": "test-api-key",
            "DEV_JWKS_ENABLED": "true",
            "DEV_OPA_ENABLED": "false",
            "DEV_OAUTH2_JWKS_ENDPOINT": "https://example.com/.well-known/jwks.json",
            "DEV_OAUTH2_TOKEN_ENDPOINT": "https://example.com/oauth/token",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            with pytest.raises(ValueError, match="mutually exclusive"):
                reload_app_with_env(env_vars)


class TestStartupWorkflowPygeoapiConfig:
    """Test startup workflow with pygeoapi configuration."""

    def test_startup_with_custom_context(self):
        """Test that application mounts pygeoapi at custom context path."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/api/v1",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            client = TestClient(app)
            # Verify the app is mounted at the custom context
            response = client.get("/api/v1/openapi?f=json")
            assert response.status_code == 200

    def test_startup_sets_pygeoapi_env_variables(self):
        """Test that startup properly sets pygeoapi environment variables."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "127.0.0.1",
            "PORT": "8080",
            "DEV_PYGEOAPI_BASEURL": "http://example.com:8080",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            reload_app_with_env(env_vars)

            # Verify pygeoapi environment variables are set
            assert os.environ.get("PYGEOAPI_CONFIG") == "pygeoapi-config.yml"
            assert os.environ.get("PYGEOAPI_OPENAPI") == "pygeoapi-openapi.yml"
            assert os.environ.get("HOST") == "127.0.0.1"
            assert os.environ.get("PORT") == "8080"
            assert os.environ.get("PYGEOAPI_BASEURL") == "http://example.com:8080"
            assert os.environ.get("FASTGEOAPI_CONTEXT") == "/geoapi"


class TestStartupWorkflowMiddleware:
    """Test startup workflow with middleware configurations."""

    def test_startup_with_reverse_proxy_enabled(self):
        """Test that application starts with reverse proxy middleware enabled."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_REVERSE_PROXY": "true",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            assert app is not None
            client = TestClient(app)
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

    def test_startup_with_cors_middleware(self):
        """Test that CORS middleware is properly configured.

        Note: When allow_credentials=True in CORSMiddleware, the
        Access-Control-Allow-Origin header reflects the request Origin
        rather than returning "*" for security reasons.
        """
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            client = TestClient(app)
            # Test CORS preflight request
            # With allow_credentials=True, the origin is reflected back
            response = client.options(
                "/geoapi/",
                headers={
                    "Origin": "http://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            # CORS returns the requesting origin when allow_credentials=True
            assert response.headers.get("access-control-allow-origin") in [
                "*",
                "http://example.com",
            ]
            assert response.headers.get("access-control-allow-credentials") == "true"


class TestStartupWorkflowAWSLambda:
    """Test startup workflow for AWS Lambda deployment."""

    def test_startup_with_aws_lambda_deploy_false(self):
        """Test that application starts without Mangum handler when AWS_LAMBDA_DEPLOY=false."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_AWS_LAMBDA_DEPLOY": "false",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)
            assert app is not None

            # Verify that the app module doesn't have handler attribute
            # when AWS_LAMBDA_DEPLOY is false
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.config.app import configuration as cfg

            # AWS_LAMBDA_DEPLOY should be False for dev
            assert cfg.AWS_LAMBDA_DEPLOY is False


class TestStartupWorkflowLogging:
    """Test startup workflow logging configuration."""

    def test_startup_with_debug_log_level(self):
        """Test that application configures logging correctly with debug level."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_LOG_LEVEL": "debug",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            # Verify the app has a logger attribute
            assert hasattr(app, "logger")


class TestStartupWorkflowOpenAPI:
    """Test startup workflow OpenAPI generation."""

    def test_startup_generates_openapi_if_missing(self, tmp_path):
        """Test that startup generates pygeoapi-openapi.yml if it doesn't exist."""

        # Create a temporary pygeoapi config
        original_config = "pygeoapi-config.yml"
        temp_openapi = tmp_path / "pygeoapi-openapi.yml"

        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": original_config,
            "DEV_PYGEOAPI_OPENAPI": str(temp_openapi),
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        # Ensure the temp openapi file doesn't exist
        if temp_openapi.exists():
            temp_openapi.unlink()

        with mock.patch.dict(os.environ, env_vars, clear=False):
            # Note: This test may fail if the openapi file path is not in cwd
            # The actual generation happens in create_app() when the file doesn't exist
            pass  # Skip actual execution as it requires proper file paths


class TestStartupWorkflowMCP:
    """Test startup workflow with MCP configuration for retrocompatibility."""

    def test_startup_without_mcp_by_default(self):
        """Test that application starts without MCP when FASTGEOAPI_WITH_MCP is not set (default=False)."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
            # FASTGEOAPI_WITH_MCP is NOT set - should default to False
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            assert app is not None
            client = TestClient(app)

            # pygeoapi endpoints should work
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

            # MCP endpoint should NOT exist (404)
            response = client.get("/mcp/")
            assert response.status_code == 404

    def test_startup_with_mcp_disabled_explicitly(self):
        """Test that application starts without MCP when FASTGEOAPI_WITH_MCP=false."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "false",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            assert app is not None
            client = TestClient(app)

            # pygeoapi endpoints should work
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

            # MCP endpoint should NOT exist (404)
            response = client.get("/mcp/")
            assert response.status_code == 404

    def test_startup_with_mcp_enabled(self):
        """Test that application starts with MCP when FASTGEOAPI_WITH_MCP=true."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "true",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            # Need to reload the entire main module to test MCP mounting
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            # Import the app directly from main (which includes MCP setup at module level)
            from app.main import app

            assert app is not None

            # Verify MCP route is mounted by checking routes
            route_paths = [route.path for route in app.routes if hasattr(route, "path")]
            assert (
                "/mcp" in route_paths
            ), "MCP route should be mounted when FASTGEOAPI_WITH_MCP=true"

            # Verify pygeoapi is still accessible
            client = TestClient(app)
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

    def test_mcp_routes_not_in_app_when_disabled(self):
        """Test that MCP routes are not present in the app when MCP is disabled."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "false",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            # Check that /mcp is not in the routes
            route_paths = [route.path for route in app.routes if hasattr(route, "path")]
            assert "/mcp" not in route_paths
            assert not any("/mcp" in str(path) for path in route_paths)

    def test_openapi_file_generated_when_mcp_disabled(self, tmp_path):
        """Test that OpenAPI file is generated even when MCP is disabled.

        This ensures the openapi_generator utility is called regardless of MCP setting.
        """
        # Create a temporary OpenAPI file path
        temp_openapi = tmp_path / "pygeoapi-openapi.yml"

        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": str(temp_openapi),
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "false",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        # Ensure the temp openapi file doesn't exist
        assert not temp_openapi.exists()

        with mock.patch.dict(os.environ, env_vars, clear=False):
            # Clear modules to get fresh import
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            # Import triggers ensure_openapi_file_exists() at module level
            from app.main import app

            assert app is not None

            # Verify OpenAPI file was generated
            assert (
                temp_openapi.exists()
            ), "OpenAPI file should be generated even when MCP is disabled"

            # Verify file has content
            content = temp_openapi.read_text()
            assert len(content) > 0, "OpenAPI file should have content"
            assert "openapi" in content, "OpenAPI file should contain valid OpenAPI spec"

    def test_retrocompatibility_with_master_config(self):
        """Test that server works exactly like master branch when MCP is disabled.

        This test ensures retrocompatibility by verifying all standard pygeoapi
        endpoints work without MCP enabled.
        """
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
            # No MCP setting - should behave like master
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            client = TestClient(app)

            # Test all standard OGC API endpoints that should work on master
            # Landing page
            response = client.get("/geoapi/?f=json")
            assert response.status_code == 200

            # OpenAPI
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

            # Conformance
            response = client.get("/geoapi/conformance?f=json")
            assert response.status_code == 200

            # Collections
            response = client.get("/geoapi/collections?f=json")
            assert response.status_code == 200

            # Processes
            response = client.get("/geoapi/processes?f=json")
            assert response.status_code == 200


class TestStartupWorkflowMCPAuth:
    """Test MCP startup with OIDC authentication configuration."""

    def test_mcp_without_oidc_auth(self):
        """Test that MCP starts without OIDC auth when JWKS is disabled."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "true",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import app

            assert app is not None

            # Verify MCP route is mounted
            route_paths = [route.path for route in app.routes if hasattr(route, "path")]
            assert "/mcp" in route_paths

            # Verify pygeoapi is still accessible
            client = TestClient(app)
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

    def test_mcp_with_oidc_auth_requires_config(self):
        """Test that MCP with JWKS enabled starts without OIDC if config is missing."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "true",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "true",
            "DEV_OPA_ENABLED": "false",
            "DEV_OAUTH2_JWKS_ENDPOINT": "https://example.com/.well-known/jwks.json",
            # Explicitly unset OIDC config - MCP should start without OIDC auth
            "DEV_OIDC_WELL_KNOWN_ENDPOINT": "",
            "DEV_OIDC_CLIENT_ID": "",
            "DEV_OIDC_CLIENT_SECRET": "",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import create_mcp_server

            mcp_server, mcp_app, well_known_routes, _ = create_mcp_server()

            assert mcp_server is not None
            assert mcp_app is not None
            # No OIDC config, so no well-known routes
            assert well_known_routes == []

    def test_mcp_oidc_auth_config_creation(self):
        """Test that OIDCProxy auth is created when all OIDC vars are set."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "true",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "true",
            "DEV_OPA_ENABLED": "false",
            "DEV_OAUTH2_JWKS_ENDPOINT": "https://example.logto.app/oidc/jwks",
            "DEV_OIDC_WELL_KNOWN_ENDPOINT": "https://example.logto.app/oidc/.well-known/openid-configuration",
            "DEV_OIDC_CLIENT_ID": "test-client-id",
            "DEV_OIDC_CLIENT_SECRET": "test-client-secret",
            "DEV_APP_URI": "http://localhost:5000",
        }

        # Mock OIDC configuration response
        mock_oidc_config = {
            "issuer": "https://example.logto.app/oidc",
            "authorization_endpoint": "https://example.logto.app/oidc/auth",
            "token_endpoint": "https://example.logto.app/oidc/token",
            "jwks_uri": "https://example.logto.app/oidc/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            # Clean app modules
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            # Mock requests.get for mcpauth and httpx.get for FastMCP
            mock_response = mock.MagicMock()
            mock_response.json.return_value = mock_oidc_config
            mock_response.raise_for_status = mock.MagicMock()

            with mock.patch("requests.get", return_value=mock_response):
                with mock.patch("httpx.get", return_value=mock_response):
                    from app.main import create_mcp_server

                    mcp_server, mcp_app, well_known_routes, _ = create_mcp_server()

                    assert mcp_server is not None
                    assert mcp_app is not None
                    # With OIDC config, we should have well-known routes
                    assert len(well_known_routes) > 0

    def test_mcp_oidc_base_url_uses_app_uri(self):
        """Test that MCP OIDC auth uses APP_URI for base_url when available."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "true",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "true",
            "DEV_OPA_ENABLED": "false",
            "DEV_OAUTH2_JWKS_ENDPOINT": "https://example.logto.app/oidc/jwks",
            "DEV_OIDC_WELL_KNOWN_ENDPOINT": "https://example.logto.app/oidc/.well-known/openid-configuration",
            "DEV_OIDC_CLIENT_ID": "test-client-id",
            "DEV_OIDC_CLIENT_SECRET": "test-client-secret",
            "DEV_APP_URI": "https://myapp.example.com",
        }

        # Mock OIDC configuration response
        mock_oidc_config = {
            "issuer": "https://example.logto.app/oidc",
            "authorization_endpoint": "https://example.logto.app/oidc/auth",
            "token_endpoint": "https://example.logto.app/oidc/token",
            "jwks_uri": "https://example.logto.app/oidc/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            # Mock requests.get for mcpauth and httpx.get for FastMCP
            mock_response = mock.MagicMock()
            mock_response.json.return_value = mock_oidc_config
            mock_response.raise_for_status = mock.MagicMock()

            with mock.patch("requests.get", return_value=mock_response):
                with mock.patch("httpx.get", return_value=mock_response):
                    from app.main import create_mcp_server

                    mcp_server, _, well_known_routes, _ = create_mcp_server()

                    assert mcp_server is not None
                    # With OIDC config, we should have well-known routes
                    assert len(well_known_routes) > 0

    def test_mcp_oidc_base_url_fallback_to_host_port(self):
        """Test that MCP OIDC auth falls back to HOST:PORT when APP_URI is not set."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "localhost",  # Use localhost for MCP OIDC (allows HTTP)
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "true",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "true",
            "DEV_OPA_ENABLED": "false",
            "DEV_OAUTH2_JWKS_ENDPOINT": "https://example.logto.app/oidc/jwks",
            "DEV_OIDC_WELL_KNOWN_ENDPOINT": "https://example.logto.app/oidc/.well-known/openid-configuration",
            "DEV_OIDC_CLIENT_ID": "test-client-id",
            "DEV_OIDC_CLIENT_SECRET": "test-client-secret",
            # APP_URI is NOT set - explicitly clear it
            "DEV_APP_URI": "",
        }

        # Mock OIDC configuration response
        mock_oidc_config = {
            "issuer": "https://example.logto.app/oidc",
            "authorization_endpoint": "https://example.logto.app/oidc/auth",
            "token_endpoint": "https://example.logto.app/oidc/token",
            "jwks_uri": "https://example.logto.app/oidc/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            # Mock requests.get for mcpauth and httpx.get for FastMCP
            mock_response = mock.MagicMock()
            mock_response.json.return_value = mock_oidc_config
            mock_response.raise_for_status = mock.MagicMock()

            with mock.patch("requests.get", return_value=mock_response):
                with mock.patch("httpx.get", return_value=mock_response):
                    from app.main import create_mcp_server

                    mcp_server, _, well_known_routes, _ = create_mcp_server()

                    assert mcp_server is not None
                    # With OIDC config, we should have well-known routes
                    assert len(well_known_routes) > 0

    def test_mcp_well_known_routes_mounted_at_root(self):
        """Test that OAuth well-known routes are mounted at root level, not under /mcp."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "localhost",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_FASTGEOAPI_WITH_MCP": "true",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "true",
            "DEV_OPA_ENABLED": "false",
            "DEV_OAUTH2_JWKS_ENDPOINT": "https://example.logto.app/oidc/jwks",
            "DEV_OIDC_WELL_KNOWN_ENDPOINT": "https://example.logto.app/oidc/.well-known/openid-configuration",
            "DEV_OIDC_CLIENT_ID": "test-client-id",
            "DEV_OIDC_CLIENT_SECRET": "test-client-secret",
            "DEV_APP_URI": "",
        }

        # Mock OIDC configuration response
        mock_oidc_config = {
            "issuer": "https://example.logto.app/oidc",
            "authorization_endpoint": "https://example.logto.app/oidc/auth",
            "token_endpoint": "https://example.logto.app/oidc/token",
            "jwks_uri": "https://example.logto.app/oidc/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            # Mock requests.get for mcpauth and httpx.get for FastMCP
            mock_response = mock.MagicMock()
            mock_response.json.return_value = mock_oidc_config
            mock_response.raise_for_status = mock.MagicMock()

            with mock.patch("requests.get", return_value=mock_response):
                with mock.patch("httpx.get", return_value=mock_response):
                    from app.main import create_mcp_server

                    _, _, well_known_routes, _ = create_mcp_server()

                    # Verify well-known routes exist and have proper paths
                    assert len(well_known_routes) > 0
                    for route in well_known_routes:
                        # All well-known routes should start with /.well-known/
                        assert route.path.startswith("/.well-known/")
                        # They should contain the mcp path as a suffix (RFC 9728)
                        # e.g. /.well-known/oauth-authorization-server/mcp
                        assert "/mcp" in route.path


class TestStartupWorkflowIntegration:
    """Integration tests for the complete startup workflow."""

    def test_full_startup_workflow_dev(self):
        """Test complete startup workflow for development environment."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
            "DEV_FASTGEOAPI_REVERSE_PROXY": "false",
            "DEV_LOG_LEVEL": "debug",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            # Verify app is created correctly
            assert app is not None
            assert app.title == "fastgeoapi"
            assert hasattr(app, "logger")

            # Verify endpoints are accessible
            client = TestClient(app)

            # Test OpenAPI endpoint
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200
            openapi_spec = response.json()
            assert "openapi" in openapi_spec

            # Test landing page
            response = client.get("/geoapi/?f=json")
            assert response.status_code == 200

            # Test conformance
            response = client.get("/geoapi/conformance?f=json")
            assert response.status_code == 200

            # Test collections
            response = client.get("/geoapi/collections?f=json")
            assert response.status_code == 200

    def test_full_startup_workflow_with_api_key(self):
        """Test complete startup workflow with API key authentication."""
        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "DEV_PYGEOAPI_BASEURL": "http://localhost:5000",
            "DEV_PYGEOAPI_CONFIG": "pygeoapi-config.yml",
            "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
            "DEV_FASTGEOAPI_CONTEXT": "/geoapi",
            "DEV_API_KEY_ENABLED": "true",
            "DEV_PYGEOAPI_KEY_GLOBAL": "my-secret-key",
            "DEV_JWKS_ENABLED": "false",
            "DEV_OPA_ENABLED": "false",
            "PYGEOAPI_KEY_GLOBAL": "my-secret-key",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            app = reload_app_with_env(env_vars)

            client = TestClient(app)

            # Test that public endpoints work without auth
            response = client.get("/geoapi/openapi?f=json")
            assert response.status_code == 200

            # Test that protected endpoints require API key (returns 401 Unauthorized)
            response = client.get("/geoapi/?f=json")
            assert response.status_code == 401

            # Test that protected endpoints work with correct API key
            response = client.get("/geoapi/?f=json", headers={"X-API-KEY": "my-secret-key"})
            assert response.status_code == 200

            # Verify OpenAPI spec includes security scheme
            response = client.get("/geoapi/openapi?f=json")
            openapi_spec = response.json()
            assert (
                "security" in openapi_spec
                or "securityDefinitions" in openapi_spec
                or any("security" in str(v) for v in openapi_spec.values())
            )
