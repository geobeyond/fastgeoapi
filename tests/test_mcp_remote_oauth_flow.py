"""End-to-end tests for mcp-remote OAuth flow.

These tests simulate the complete OAuth flow that mcp-remote performs:
1. OAuth Server Discovery (/.well-known/oauth-authorization-server/mcp)
2. Dynamic Client Registration (POST /mcp/register)
3. Authorization Request (GET /mcp/authorize)
4. Token Exchange (POST /mcp/token)
5. Authenticated MCP Request (POST /mcp/)

These tests are designed to run in CI/CD without requiring a real IdP.
"""

import hashlib
import secrets
from base64 import urlsafe_b64encode
from unittest.mock import MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient


@pytest.fixture
def mock_oidc_config():
    """Mock OIDC configuration from IdP."""
    return {
        "issuer": "https://example.logto.app/oidc",
        "authorization_endpoint": "https://example.logto.app/oidc/auth",
        "token_endpoint": "https://example.logto.app/oidc/token",
        "jwks_uri": "https://example.logto.app/oidc/jwks",
        "introspection_endpoint": "https://example.logto.app/oidc/token/introspection",
        "response_types_supported": ["code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_basic",
            "client_secret_post",
        ],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
    }


@pytest.fixture
def mcp_test_app(mock_oidc_config):
    """Create a test MCP app with mocked OIDC configuration."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_oidc_config
    mock_response.raise_for_status = MagicMock()

    with patch("fastmcp.server.auth.oidc_proxy.httpx.get", return_value=mock_response):
        with patch("requests.get", return_value=mock_response):
            from app.auth.mcp_auth_provider import (
                OIDCProxyWithoutResource,
                TrustingUpstreamTokenVerifier,
                patch_fastmcp_auth_middleware,
            )

            # Patch FastMCP's middleware for RFC 6750 compliance
            patch_fastmcp_auth_middleware()

            token_verifier = TrustingUpstreamTokenVerifier(
                client_id="test-client",
                client_secret="test-secret",
                required_scopes=["openid", "profile", "email"],
            )

            auth = OIDCProxyWithoutResource(
                config_url="https://example.logto.app/oidc/.well-known/openid-configuration",
                client_id="test-client",
                client_secret="test-secret",
                base_url="http://localhost:5000/mcp/",
                token_verifier=token_verifier,
            )

            from fastmcp import FastMCP

            mcp = FastMCP("Test MCP Server", auth=auth)
            mcp_app = mcp.http_app(path="/")

            # Get well-known routes
            well_known_routes = auth.get_well_known_routes(mcp_path="/")

            app = Starlette(routes=[Mount("/mcp", app=mcp_app)])

            # Add well-known routes at root level
            for route in well_known_routes:
                app.router.routes.insert(0, route)

            yield TestClient(app, raise_server_exceptions=False)


class TestMCPRemoteOAuthFlowE2E:
    """End-to-end tests simulating the complete mcp-remote OAuth flow.

    This test class reproduces the exact sequence of HTTP requests that
    mcp-remote makes when connecting to an MCP server with OAuth.
    """

    def test_step1_oauth_server_discovery(self, mcp_test_app):
        """Step 1: mcp-remote discovers OAuth server configuration.

        mcp-remote first fetches /.well-known/oauth-authorization-server/mcp
        to discover the OAuth endpoints (authorization, token, registration).
        """
        response = mcp_test_app.get("/.well-known/oauth-authorization-server/mcp")

        assert response.status_code == 200
        data = response.json()

        # Verify required OAuth metadata fields
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data
        assert "response_types_supported" in data
        assert "grant_types_supported" in data
        assert "code_challenge_methods_supported" in data

        # Verify PKCE support (required by mcp-remote)
        assert "S256" in data["code_challenge_methods_supported"]

        # Verify authorization_code grant type
        assert "authorization_code" in data["grant_types_supported"]

    def test_step2_dynamic_client_registration(self, mcp_test_app):
        """Step 2: mcp-remote registers itself as an OAuth client via DCR.

        After discovering the registration_endpoint, mcp-remote registers
        itself with redirect_uri pointing to its local callback server.
        """
        # First get the registration endpoint to verify discovery works
        discovery = mcp_test_app.get("/.well-known/oauth-authorization-server/mcp")
        assert "registration_endpoint" in discovery.json()

        # Simulate mcp-remote's DCR request
        dcr_request = {
            "client_name": "mcp-remote-test",
            "redirect_uris": ["http://127.0.0.1:8265/oauth/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "openid profile email",
        }

        response = mcp_test_app.post(
            "/mcp/register",
            json=dcr_request,
            headers={"Content-Type": "application/json"},
        )

        # DCR returns 201 Created per RFC 7591
        assert response.status_code in [200, 201]
        data = response.json()

        # Verify client credentials are returned
        assert "client_id" in data
        assert "client_secret" in data
        assert len(data["client_id"]) > 0
        assert len(data["client_secret"]) > 0

        # Verify redirect_uris are echoed back
        assert "redirect_uris" in data
        assert "http://127.0.0.1:8265/oauth/callback" in data["redirect_uris"]

    def test_step3_initial_mcp_request_triggers_auth(self, mcp_test_app):
        """Step 3: Initial MCP request without token returns 401.

        When mcp-remote first tries to connect to the MCP endpoint,
        it receives a 401 that triggers the OAuth flow.

        CRITICAL: The error must NOT be 'invalid_token' or mcp-remote
        will delete its client credentials.
        """
        response = mcp_test_app.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-remote", "version": "1.0.0"},
                },
                "id": 1,
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )

        assert response.status_code == 401

        # Check response body
        body = response.json()
        assert body.get("error") == "unauthorized"

        # CRITICAL: Verify invalid_token is NOT in the response
        # This is the key fix for mcp-remote compatibility
        www_auth = response.headers.get("WWW-Authenticate", "")
        assert 'error="invalid_token"' not in www_auth, (
            "Server must NOT return 'invalid_token' when no token is provided. "
            "This causes mcp-remote to delete client credentials."
        )

        # Verify WWW-Authenticate header is present
        assert "Bearer" in www_auth

    def test_step4_authorization_request_redirects_to_idp(self, mcp_test_app):
        """Step 4: Authorization request redirects to upstream IdP.

        mcp-remote builds an authorization URL with PKCE and redirects
        the user's browser to the MCP server's authorize endpoint.
        """
        # First register a client
        dcr_response = mcp_test_app.post(
            "/mcp/register",
            json={
                "client_name": "test-client",
                "redirect_uris": ["http://127.0.0.1:8265/oauth/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert dcr_response.status_code in [200, 201], f"DCR failed: {dcr_response.text}"
        client_id = dcr_response.json()["client_id"]

        # Generate PKCE challenge (like mcp-remote does)
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = (
            urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
        )

        # Build authorization request
        auth_params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "http://127.0.0.1:8265/oauth/callback",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(16),
            "scope": "openid profile email",
        }

        response = mcp_test_app.get(
            "/mcp/authorize",
            params=auth_params,
            follow_redirects=False,
        )

        # Should redirect to consent page or upstream IdP
        assert response.status_code in [302, 303, 307]

        # Get the redirect location
        location = response.headers.get("Location", "")
        assert len(location) > 0

    def test_step5_invalid_token_returns_proper_error(self, mcp_test_app):
        """Step 5: Request with invalid token returns invalid_token error.

        When a token IS provided but is invalid, the server SHOULD
        return 'invalid_token' error per RFC 6750.
        """
        response = mcp_test_app.post(
            "/mcp/",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
                "id": 1,
            },
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer invalid-token-xyz",
            },
        )

        assert response.status_code == 401

        www_auth = response.headers.get("WWW-Authenticate", "")
        # For an actual invalid token, invalid_token IS correct
        assert 'error="invalid_token"' in www_auth

    def test_full_dcr_flow_preserves_client_credentials(self, mcp_test_app):
        """Test that the full DCR flow doesn't cause credential loss.

        This test simulates the exact sequence that was causing issues:
        1. Register client via DCR
        2. Make unauthenticated request (should NOT trigger credential deletion)
        3. Verify client can still be used

        The bug was: step 2 returned 'invalid_token' which caused mcp-remote
        to call invalidateCredentials("all"), deleting the client_info.json
        """
        # Step 1: Register client
        dcr_response = mcp_test_app.post(
            "/mcp/register",
            json={
                "client_name": "mcp-remote-simulation",
                "redirect_uris": ["http://127.0.0.1:9999/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert dcr_response.status_code in [200, 201], f"DCR failed: {dcr_response.text}"
        client_data = dcr_response.json()
        client_id = client_data["client_id"]

        # Step 2: Make unauthenticated MCP request
        unauth_response = mcp_test_app.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={"Content-Type": "application/json"},
        )

        # Should get 401 but NOT with invalid_token
        assert unauth_response.status_code == 401
        www_auth = unauth_response.headers.get("WWW-Authenticate", "")
        assert (
            'error="invalid_token"' not in www_auth
        ), "Unauthenticated request should not return invalid_token"

        # Step 3: Client should still be valid for authorization
        # (In real flow, mcp-remote would now start the OAuth dance)
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = (
            urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
        )

        auth_response = mcp_test_app.get(
            "/mcp/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:9999/callback",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "state": "test-state",
                "scope": "openid profile email",
            },
            follow_redirects=False,
        )

        # Should redirect (to consent or IdP), not error
        assert auth_response.status_code in [302, 303, 307], (
            f"Expected redirect, got {auth_response.status_code}. "
            "Client credentials may have been invalidated."
        )


class TestMCPRemoteCompatibility:
    """Tests for specific mcp-remote compatibility requirements."""

    def test_localhost_redirect_uris_allowed(self, mcp_test_app):
        """Test that localhost redirect URIs are allowed for DCR.

        mcp-remote uses localhost callback servers, so the MCP server
        must allow these redirect URIs.
        """
        localhost_uris = [
            "http://localhost:8080/callback",
            "http://127.0.0.1:8080/callback",
            "http://localhost:23456/oauth/callback",
            "http://127.0.0.1:0/callback",  # Dynamic port
        ]

        for uri in localhost_uris:
            response = mcp_test_app.post(
                "/mcp/register",
                json={
                    "client_name": f"test-{uri}",
                    "redirect_uris": [uri],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                },
            )
            assert response.status_code in [
                200,
                201,
            ], f"Redirect URI {uri} should be allowed. Error: {response.text}"

    def test_pkce_s256_required(self, mcp_test_app):
        """Test that PKCE with S256 is supported.

        mcp-remote always uses PKCE for security.
        """
        discovery = mcp_test_app.get("/.well-known/oauth-authorization-server/mcp")
        data = discovery.json()

        assert "code_challenge_methods_supported" in data
        assert "S256" in data["code_challenge_methods_supported"]

    def test_client_secret_post_auth_method_supported(self, mcp_test_app):
        """Test that client_secret_post auth method is supported.

        mcp-remote typically uses client_secret_post for token exchange.
        """
        discovery = mcp_test_app.get("/.well-known/oauth-authorization-server/mcp")
        data = discovery.json()

        assert "token_endpoint_auth_methods_supported" in data
        assert "client_secret_post" in data["token_endpoint_auth_methods_supported"]

    def test_refresh_token_grant_supported(self, mcp_test_app):
        """Test that refresh_token grant is supported.

        mcp-remote uses refresh tokens for long-lived sessions.
        """
        discovery = mcp_test_app.get("/.well-known/oauth-authorization-server/mcp")
        data = discovery.json()

        assert "grant_types_supported" in data
        assert "refresh_token" in data["grant_types_supported"]


class TestRFC6750Compliance:
    """Tests for RFC 6750 (Bearer Token Usage) compliance."""

    def test_no_token_returns_401_without_error_code(self, mcp_test_app):
        """Per RFC 6750 Section 3.1: No error code when token is missing.

        When no token is provided, the response should be 401 with
        WWW-Authenticate header but WITHOUT an error code.
        """
        response = mcp_test_app.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 401

        www_auth = response.headers.get("WWW-Authenticate", "")
        assert www_auth.startswith("Bearer")

        # Should NOT have invalid_token error
        assert 'error="invalid_token"' not in www_auth

    def test_malformed_token_returns_invalid_token(self, mcp_test_app):
        """Per RFC 6750: Malformed token should return invalid_token."""
        response = mcp_test_app.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer malformed.token.here",
            },
        )

        assert response.status_code == 401

        www_auth = response.headers.get("WWW-Authenticate", "")
        assert 'error="invalid_token"' in www_auth

    def test_www_authenticate_header_format(self, mcp_test_app):
        """Test WWW-Authenticate header follows RFC 6750 format."""
        response = mcp_test_app.post(
            "/mcp/",
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
        )

        assert response.status_code == 401

        www_auth = response.headers.get("WWW-Authenticate", "")

        # Must start with Bearer
        assert www_auth.startswith("Bearer")

        # Should include realm
        assert "realm=" in www_auth
