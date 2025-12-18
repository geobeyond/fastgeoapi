"""Test cases for OPA/OIDC integration.

This module tests the fastgeoapi application with OPA (Open Policy Agent)
enabled for authorization. It uses a mock OPA server that returns configurable
allow/deny decisions, simulating policies from scripts/iam/policy/auth.rego.

The tests verify that:
1. The application starts correctly with OPA_ENABLED=true
2. Requests are authorized when OPA returns allow=true
3. Requests are denied when OPA returns allow=false
4. The OPA middleware correctly integrates with the OIDC authentication flow

Note: OIDC authentication is mocked to isolate OPA authorization testing.
pytest-iam was evaluated but has compatibility issues with current Pydantic.
See: https://github.com/pydantic/pydantic/issues/10551
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

import pytest
import schemathesis
from hypothesis import Phase, settings


class MockOPAAllowHandler(BaseHTTPRequestHandler):
    """Mock OPA server handler that always allows requests.

    Simulates the OPA policy: default allow = true
    """

    def do_POST(self):
        """Handle POST requests to OPA decision endpoint."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Log the input for debugging
        try:
            input_data = json.loads(body)
            # The input contains user info and request details
            _ = input_data.get("input", {})
        except json.JSONDecodeError:
            pass

        # Always return allow: true (simulating default allow = true)
        response = {"result": {"allow": True}}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        """Suppress HTTP server logs during tests."""


class MockOPADenyHandler(BaseHTTPRequestHandler):
    """Mock OPA server handler that always denies requests.

    Simulates the OPA policy: default allow = false
    """

    def do_POST(self):
        """Handle POST requests to OPA decision endpoint."""
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Log the input for debugging
        try:
            input_data = json.loads(body)
            # The input contains user info and request details
            _ = input_data.get("input", {})
        except json.JSONDecodeError:
            pass

        # Always return allow: false (simulating default allow = false)
        response = {"result": {"allow": False}}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())

    def log_message(self, format, *args):
        """Suppress HTTP server logs during tests."""


class MockOPAServer:
    """Context manager for running a mock OPA server."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        handler: type[BaseHTTPRequestHandler] = MockOPAAllowHandler,
    ):
        """Initialize the mock OPA server.

        Args:
            host: Host to bind to.
            port: Port to bind to. Use 0 for automatic port assignment.
            handler: The request handler class to use (allow or deny).
        """
        self.host = host
        self.requested_port = port
        self.handler = handler
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._actual_port: int = 0

    def __enter__(self):
        """Start the mock OPA server."""
        self.server = HTTPServer((self.host, self.requested_port), self.handler)
        self.server.allow_reuse_address = True
        self._actual_port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop the mock OPA server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=5)

    @property
    def port(self) -> int:
        """Return the actual port the server is listening on."""
        return self._actual_port

    @property
    def url(self) -> str:
        """Return the OPA decision endpoint URL."""
        return f"http://{self.host}:{self.port}/v1/data/httpapi/authz"


@pytest.fixture
def mock_opa_server():
    """Fixture that provides a running mock OPA server that allows all requests.

    Uses port 0 for automatic port assignment to avoid conflicts.
    """
    with MockOPAServer(handler=MockOPAAllowHandler) as server:
        yield server


@pytest.fixture
def mock_opa_deny_server():
    """Fixture that provides a running mock OPA server that denies all requests.

    Uses port 0 for automatic port assignment to avoid conflicts.
    """
    with MockOPAServer(handler=MockOPADenyHandler) as server:
        yield server


@pytest.fixture
def mock_oidc_authenticate():
    """Fixture that mocks OIDC authentication to return a valid user.

    This mocks the OIDCAuthentication.authenticate method to bypass
    the actual OIDC flow and return a test user with attributes that
    can be used in OPA policy decisions.
    """
    user_info = {
        "sub": "test-user-id",
        "email": "test@example.com",
        "preferred_username": "testuser",
        "company": "geobeyond",
        "user": "testuser",
    }

    with mock.patch(
        "fastapi_opa.auth.auth_oidc.OIDCAuthentication.authenticate",
        return_value=user_info,
    ):
        yield user_info


@pytest.fixture
def create_opa_protected_app(mock_opa_server, mock_oidc_authenticate):
    """Create an app with OPA protection enabled.

    Uses a mock OPA server for authorization decisions and mocks
    OIDC authentication to return a valid user.
    """

    def _create_app():
        # Remove all app modules to ensure clean reload with new environment
        modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
        for module in modules_to_remove:
            del sys.modules[module]

        env_vars = {
            "ENV_STATE": "dev",
            "HOST": "0.0.0.0",
            "PORT": "5000",
            "OPA_ENABLED": "true",
            "DEV_OPA_ENABLED": "true",
            "DEV_OPA_URL": mock_opa_server.url,
            "DEV_APP_URI": "http://localhost:5000",
            # Use Logto OIDC configuration (real endpoint for app startup)
            "DEV_OIDC_WELL_KNOWN_ENDPOINT": "https://76hxgq.logto.app/oidc/.well-known/openid-configuration",
            "DEV_OIDC_CLIENT_ID": "s4rf23nynrcotc86xnieq",
            "DEV_OIDC_CLIENT_SECRET": "W6DraAbu16goorGLVHM6XYRRr8ijNmL0",
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
        }

        with mock.patch.dict(os.environ, env_vars, clear=False):
            # Clear the configuration cache inside the context
            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import app

            return app

    yield _create_app


@pytest.fixture
def opa_protected_app(create_opa_protected_app):
    """Return the OPA protected app instance."""
    return create_opa_protected_app()


@pytest.fixture
def protected_opa_schema(create_opa_protected_app):
    """Create an OPA protected schema for contract testing.

    Note: In schemathesis 4.x, filters must be applied on the LazySchema
    returned by from_fixture(), not on the schema in the fixture.
    """
    app = create_opa_protected_app()
    return schemathesis.openapi.from_asgi("/geoapi/openapi?f=json", app=app)


# Set environment variable for skipif decorator
os.environ["OPA_ENABLED"] = "true"

# In schemathesis 4.x, filters must be applied on the LazySchema
schema_opa = (
    schemathesis.pytest.from_fixture("protected_opa_schema")
    .exclude(method="POST", path_regex=r".*/items$")
    .exclude(method="OPTIONS")
)


@pytest.mark.skipif(
    os.environ.get("OPA_ENABLED", "").lower() not in ("true", "1"),
    reason="Skipping OPA tests when OPA is not enabled",
)
@schema_opa.parametrize()
@settings(max_examples=50, deadline=10000, phases=[Phase.generate])
def test_api_with_opa(case, mock_opa_server, mock_oidc_authenticate):
    """Test the API with OPA protection when access is allowed.

    This test uses:
    - Mock OPA server: Returns allow=true for all requests
    - Mock OIDC authentication: Returns a valid user

    Simulates the simple auth.rego policy:

        package httpapi.authz
        import input
        default allow = true
    """
    # Provide valid data for process execution endpoints
    if case.method.upper() == "POST" and "/execution" in case.path:
        case.body = {"inputs": {"name": "test-user"}}

    if case.path_parameters:
        if case.path_parameters.get("jobId"):
            job_id = case.path_parameters.get("jobId")
            if r"\n" or r"\r" in job_id:
                case.path_parameters["jobId"] = job_id.strip()
            if "%0A" in job_id:
                case.path_parameters["jobId"] = job_id.replace("%0A", "")
            if "%0D" in job_id:
                case.path_parameters["jobId"] = job_id.replace("%0D", "")

    # The mock OIDC returns a valid user, and mock OPA returns allow=true
    # So all requests should be authorized
    case.call_and_validate(checks=(schemathesis.checks.not_a_server_error,))


@pytest.mark.skipif(
    os.environ.get("OPA_ENABLED", "").lower() not in ("true", "1"),
    reason="Skipping OPA tests when OPA is not enabled",
)
def test_api_with_opa_deny(mock_opa_deny_server, mock_oidc_authenticate):
    """Test that API returns 401 when OPA denies the request.

    This test uses:
    - Mock OPA server: Returns allow=false for all requests
    - Mock OIDC authentication: Returns a valid user

    Simulates the policy:

        package httpapi.authz
        import input
        default allow = false

    Note: The fastapi-opa library returns 401 Unauthorized for both
    authentication failures and authorization denials. Ideally, authorization
    denials should return 403 Forbidden, but this is a limitation of the
    upstream library. See: https://github.com/geobeyond/fastgeoapi/issues/321
    """
    from starlette.testclient import TestClient

    env_vars = {
        "ENV_STATE": "dev",
        "HOST": "0.0.0.0",
        "PORT": "5000",
        "OPA_ENABLED": "true",
        "DEV_OPA_ENABLED": "true",
        "DEV_OPA_URL": mock_opa_deny_server.url,
        "DEV_APP_URI": "http://localhost:5000",
        # Use Logto OIDC configuration (real endpoint for app startup)
        "DEV_OIDC_WELL_KNOWN_ENDPOINT": "https://76hxgq.logto.app/oidc/.well-known/openid-configuration",
        "DEV_OIDC_CLIENT_ID": "s4rf23nynrcotc86xnieq",
        "DEV_OIDC_CLIENT_SECRET": "W6DraAbu16goorGLVHM6XYRRr8ijNmL0",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
    }

    # Remove all app modules to ensure clean reload with new environment
    modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
    for module in modules_to_remove:
        del sys.modules[module]

    with mock.patch.dict(os.environ, env_vars, clear=False):
        # Clear the configuration cache inside the context
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()

        from app.main import app as opa_deny_app

        with TestClient(opa_deny_app) as client:
            # Test a protected endpoint - should return 401 (OPA denies access)
            response = client.get("/geoapi/collections")

            # fastapi-opa returns 401 for authorization denials
            # (ideally should be 403, but this is the library's behavior)
            assert response.status_code == 401
            assert response.json() == {"message": "Unauthorized"}
