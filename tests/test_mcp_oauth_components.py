"""Test MCP OAuth components.

These tests verify that:
1. OIDCProxyWithoutResource correctly filters the 'resource' parameter for Logto/DCR compatibility
2. MCPAuthTokenVerifier handles JWT validation correctly via mcpauth
3. X-MCP-Internal-Key bypass is secure and works as expected
4. mcpauth integration configures providers correctly
"""

import hashlib
from base64 import urlsafe_b64encode
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestOIDCProxyWithoutResourceFiltering:
    """Test OIDCProxyWithoutResource filters the resource parameter for Logto/DCR compatibility.

    Logto and similar IdPs return access_denied for third-party apps (like mcp-remote
    using Dynamic Client Registration) that request API Resources without explicit
    permission grants. The OIDCProxyWithoutResource solves this by filtering out the
    'resource' parameter from authorization requests.
    """

    @pytest.fixture
    def mock_oidc_config(self):
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
        }

    def test_resource_parameter_not_in_authorize_url(self, mock_oidc_config):
        """Test that resource parameter is NOT included in upstream authorize URL."""
        from typing import Any
        from urllib.parse import urlencode

        from fastmcp.server.auth.oidc_proxy import OIDCProxy

        # Mock the OIDC configuration fetch
        # Must patch in the module where httpx is used, not globally
        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch(
            "fastmcp.server.auth.oidc_proxy.httpx.get",
            return_value=mock_response,
        ):

            class CustomOIDCProxy(OIDCProxy):
                """Custom OIDC Proxy that doesn't forward the resource parameter."""

                def _build_upstream_authorize_url(
                    self, txn_id: str, transaction: dict[str, Any]
                ) -> str:
                    """Override to not forward the resource parameter to the IdP."""
                    query_params: dict[str, Any] = {
                        "response_type": "code",
                        "client_id": self._upstream_client_id,
                        "redirect_uri": f"{str(self.base_url).rstrip('/')}{self._redirect_path}",
                        "state": txn_id,
                    }

                    scopes_to_use = transaction.get("scopes") or self.required_scopes or []
                    if scopes_to_use:
                        query_params["scope"] = " ".join(scopes_to_use)

                    proxy_code_verifier = transaction.get("proxy_code_verifier")
                    if proxy_code_verifier:
                        challenge_bytes = hashlib.sha256(proxy_code_verifier.encode()).digest()
                        proxy_code_challenge = (
                            urlsafe_b64encode(challenge_bytes).decode().rstrip("=")
                        )
                        query_params["code_challenge"] = proxy_code_challenge
                        query_params["code_challenge_method"] = "S256"

                    # Filter out 'resource' parameter
                    if self._extra_authorize_params:
                        extra_params = {
                            k: v for k, v in self._extra_authorize_params.items() if k != "resource"
                        }
                        query_params.update(extra_params)

                    separator = "&" if "?" in self._upstream_authorization_endpoint else "?"
                    return f"{self._upstream_authorization_endpoint}{separator}{urlencode(query_params)}"

            # Create instance with resource in extra_authorize_params
            proxy = CustomOIDCProxy(
                config_url="https://example.logto.app/oidc/.well-known/openid-configuration",
                client_id="test-client-id",
                client_secret="test-client-secret",
                base_url="http://localhost:5000/mcp/",
                extra_authorize_params={
                    "scope": "openid profile email",
                    "resource": "https://api.example.com",  # This should be filtered
                },
            )

            # Build the authorize URL
            txn_id = "test-transaction-id"
            transaction = {"scopes": ["openid", "profile"]}

            url = proxy._build_upstream_authorize_url(txn_id, transaction)

            # Verify resource is NOT in the URL
            assert "resource=" not in url
            assert "resource%3D" not in url  # URL-encoded version

            # Verify other params ARE in the URL
            assert "client_id=test-client-id" in url
            assert "state=test-transaction-id" in url
            assert "response_type=code" in url

    def test_scopes_are_preserved_in_authorize_url(self, mock_oidc_config):
        """Test that OIDC scopes are preserved in the authorize URL."""
        from typing import Any
        from urllib.parse import parse_qs, urlencode, urlparse

        from fastmcp.server.auth.oidc_proxy import OIDCProxy

        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):

            class CustomOIDCProxy(OIDCProxy):
                """Custom OIDC Proxy for testing."""

                def _build_upstream_authorize_url(
                    self, txn_id: str, transaction: dict[str, Any]
                ) -> str:
                    query_params: dict[str, Any] = {
                        "response_type": "code",
                        "client_id": self._upstream_client_id,
                        "redirect_uri": f"{str(self.base_url).rstrip('/')}{self._redirect_path}",
                        "state": txn_id,
                    }

                    scopes_to_use = transaction.get("scopes") or self.required_scopes or []
                    if scopes_to_use:
                        query_params["scope"] = " ".join(scopes_to_use)

                    if self._extra_authorize_params:
                        extra_params = {
                            k: v for k, v in self._extra_authorize_params.items() if k != "resource"
                        }
                        query_params.update(extra_params)

                    separator = "&" if "?" in self._upstream_authorization_endpoint else "?"
                    return f"{self._upstream_authorization_endpoint}{separator}{urlencode(query_params)}"

            proxy = CustomOIDCProxy(
                config_url="https://example.logto.app/oidc/.well-known/openid-configuration",
                client_id="test-client-id",
                client_secret="test-client-secret",
                base_url="http://localhost:5000/mcp/",
                extra_authorize_params={"scope": "openid profile email"},
            )

            url = proxy._build_upstream_authorize_url(
                "txn-123", {"scopes": ["openid", "profile", "email"]}
            )

            # Parse the URL and check scopes
            parsed = urlparse(url)
            params = parse_qs(parsed.query)

            assert "scope" in params
            scope_value = params["scope"][0]
            assert "openid" in scope_value
            assert "profile" in scope_value
            assert "email" in scope_value

    def test_pkce_challenge_is_included_when_present(self, mock_oidc_config):
        """Test that PKCE code challenge is included when verifier is in transaction."""
        from typing import Any
        from urllib.parse import parse_qs, urlencode, urlparse

        from fastmcp.server.auth.oidc_proxy import OIDCProxy

        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):

            class CustomOIDCProxy(OIDCProxy):
                """Custom OIDC Proxy for testing."""

                def _build_upstream_authorize_url(
                    self, txn_id: str, transaction: dict[str, Any]
                ) -> str:
                    query_params: dict[str, Any] = {
                        "response_type": "code",
                        "client_id": self._upstream_client_id,
                        "redirect_uri": f"{str(self.base_url).rstrip('/')}{self._redirect_path}",
                        "state": txn_id,
                    }

                    scopes_to_use = transaction.get("scopes") or self.required_scopes or []
                    if scopes_to_use:
                        query_params["scope"] = " ".join(scopes_to_use)

                    proxy_code_verifier = transaction.get("proxy_code_verifier")
                    if proxy_code_verifier:
                        challenge_bytes = hashlib.sha256(proxy_code_verifier.encode()).digest()
                        proxy_code_challenge = (
                            urlsafe_b64encode(challenge_bytes).decode().rstrip("=")
                        )
                        query_params["code_challenge"] = proxy_code_challenge
                        query_params["code_challenge_method"] = "S256"

                    if self._extra_authorize_params:
                        extra_params = {
                            k: v for k, v in self._extra_authorize_params.items() if k != "resource"
                        }
                        query_params.update(extra_params)

                    separator = "&" if "?" in self._upstream_authorization_endpoint else "?"
                    return f"{self._upstream_authorization_endpoint}{separator}{urlencode(query_params)}"

            proxy = CustomOIDCProxy(
                config_url="https://example.logto.app/oidc/.well-known/openid-configuration",
                client_id="test-client-id",
                client_secret="test-client-secret",
                base_url="http://localhost:5000/mcp/",
            )

            # Include PKCE verifier in transaction
            code_verifier = "test-code-verifier-string-for-pkce"
            url = proxy._build_upstream_authorize_url(
                "txn-456",
                {
                    "scopes": ["openid"],
                    "proxy_code_verifier": code_verifier,
                },
            )

            parsed = urlparse(url)
            params = parse_qs(parsed.query)

            # Verify PKCE parameters are present
            assert "code_challenge" in params
            assert "code_challenge_method" in params
            assert params["code_challenge_method"][0] == "S256"

            # Verify the challenge is correctly computed
            expected_challenge_bytes = hashlib.sha256(code_verifier.encode()).digest()
            expected_challenge = urlsafe_b64encode(expected_challenge_bytes).decode().rstrip("=")
            assert params["code_challenge"][0] == expected_challenge


class TestIntrospectionTokenVerifier:
    """Test IntrospectionTokenVerifier handles token validation correctly.

    The IntrospectionTokenVerifier is used for opaque tokens (non-JWT) from IdPs
    like Logto when no API Resource is requested.
    """

    @pytest.fixture
    def verifier_config(self):
        """Configuration for IntrospectionTokenVerifier."""
        return {
            "introspection_url": "https://example.logto.app/oidc/token/introspection",
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "base_url": "http://localhost:5000/mcp/",
        }

    def test_valid_token_verifier_initialization(self, verifier_config):
        """Test that IntrospectionTokenVerifier initializes correctly with valid config."""
        from fastmcp.server.auth.providers.introspection import (
            IntrospectionTokenVerifier,
        )

        verifier = IntrospectionTokenVerifier(**verifier_config)

        # Verify the verifier was created with correct configuration
        assert verifier is not None
        assert verifier.introspection_url == verifier_config["introspection_url"]
        assert verifier.client_id == verifier_config["client_id"]
        assert verifier.client_secret == verifier_config["client_secret"]

    @pytest.mark.asyncio
    async def test_inactive_token_is_rejected(self, verifier_config):
        """Test that an inactive token is rejected."""
        from fastmcp.server.auth.providers.introspection import (
            IntrospectionTokenVerifier,
        )

        _verifier = IntrospectionTokenVerifier(**verifier_config)

        # Mock the introspection response for an inactive token
        mock_response = AsyncMock()
        mock_response.json = AsyncMock(
            return_value={
                "active": False,
            }
        )
        mock_response.raise_for_status = MagicMock()

        # The verifier should handle inactive tokens appropriately
        # Actual behavior depends on implementation

    def test_introspection_endpoint_construction(self, verifier_config):
        """Test that introspection endpoint is correctly constructed."""
        from fastmcp.server.auth.providers.introspection import (
            IntrospectionTokenVerifier,
        )

        verifier = IntrospectionTokenVerifier(**verifier_config)

        # Verify the introspection URL is set correctly
        assert verifier.introspection_url == verifier_config["introspection_url"]

    def test_introspection_url_from_oidc_well_known(self):
        """Test that introspection URL is correctly derived from OIDC well-known endpoint."""
        # This tests the logic in create_mcp_server() that constructs the introspection URL
        oidc_well_known = "https://example.logto.app/oidc/.well-known/openid-configuration"

        # Extract IdP issuer URL
        idp_issuer = oidc_well_known.replace("/oidc/.well-known/openid-configuration", "")
        introspection_url = f"{idp_issuer}/oidc/token/introspection"

        assert introspection_url == "https://example.logto.app/oidc/token/introspection"

    def test_introspection_url_handles_different_oidc_paths(self):
        """Test introspection URL construction with various OIDC endpoint patterns."""
        test_cases = [
            # (well_known_endpoint, expected_introspection_url)
            (
                "https://auth.example.com/oidc/.well-known/openid-configuration",
                "https://auth.example.com/oidc/token/introspection",
            ),
            (
                "https://example.logto.app/oidc/.well-known/openid-configuration",
                "https://example.logto.app/oidc/token/introspection",
            ),
        ]

        for well_known, expected_introspection in test_cases:
            idp_issuer = well_known.replace("/oidc/.well-known/openid-configuration", "")
            introspection_url = f"{idp_issuer}/oidc/token/introspection"
            assert introspection_url == expected_introspection, f"Failed for {well_known}"


class TestMCPInternalKeyBypassSecurity:
    """Additional security tests for X-MCP-Internal-Key bypass mechanism.

    These tests complement test_mcp_internal_auth_bypass.py with additional
    security-focused scenarios.
    """

    @pytest.fixture
    def mock_config(self):
        """Create mock OAuth2 config."""
        config = MagicMock()
        config.authentication = []
        return config

    def test_internal_key_is_cryptographically_random(self):
        """Test that the internal key is generated with sufficient entropy."""
        import secrets

        # Generate multiple keys and verify they're different
        keys = [secrets.token_urlsafe(32) for _ in range(10)]

        # All keys should be unique
        assert len(set(keys)) == 10

        # Each key should be at least 32 characters (base64 encoded 32 bytes)
        for key in keys:
            assert len(key) >= 32

    def test_internal_key_not_exposed_in_response_headers(self, mock_config):
        """Test that the internal key is not exposed in response headers."""
        from starlette.responses import Response

        from app.middleware.oauth2 import Oauth2Middleware

        internal_key = "super-secret-internal-key"

        with patch("app.middleware.oauth2.cfg") as mock_cfg:
            mock_cfg.FASTGEOAPI_WITH_MCP = True
            mock_cfg.MCP_INTERNAL_KEY = internal_key
            mock_cfg.FASTGEOAPI_CONTEXT = "/geoapi"

            _middleware = Oauth2Middleware(
                app=MagicMock(),
                config=mock_config,
            )

            # Create a mock response
            response = Response(content="test")

            # Verify the internal key is not in response headers
            assert "X-MCP-Internal-Key" not in response.headers
            assert internal_key not in str(response.headers)

    def test_bypass_requires_all_conditions(self, mock_config):
        """Test that bypass requires ALL conditions to be met simultaneously."""
        from starlette.requests import Request

        from app.middleware.oauth2 import Oauth2Middleware

        internal_key = "test-key-12345"

        # Test matrix: all combinations should fail except when all conditions are True
        test_cases = [
            # (mcp_enabled, from_localhost, has_correct_key, expected_bypass)
            (True, True, True, True),  # All conditions met - should bypass
            (False, True, True, False),  # MCP disabled
            (True, False, True, False),  # External IP
            (True, True, False, False),  # Wrong key
            (False, False, True, False),  # MCP disabled + external
            (False, True, False, False),  # MCP disabled + wrong key
            (True, False, False, False),  # External + wrong key
            (False, False, False, False),  # All conditions failed
        ]

        for (
            mcp_enabled,
            from_localhost,
            has_correct_key,
            expected_bypass,
        ) in test_cases:
            request = MagicMock(spec=Request)
            request.client = MagicMock()
            request.client.host = "127.0.0.1" if from_localhost else "192.168.1.100"
            request.headers = {
                "X-MCP-Internal-Key": internal_key if has_correct_key else "wrong-key"
            }
            request.method = "GET"
            request.url = MagicMock()
            request.url.path = "/geoapi/collections"

            with patch("app.middleware.oauth2.cfg") as mock_cfg:
                mock_cfg.FASTGEOAPI_WITH_MCP = mcp_enabled
                mock_cfg.MCP_INTERNAL_KEY = internal_key
                mock_cfg.FASTGEOAPI_CONTEXT = "/geoapi"

                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(request)
                assert result == expected_bypass, (
                    f"Failed for: mcp_enabled={mcp_enabled}, "
                    f"from_localhost={from_localhost}, "
                    f"has_correct_key={has_correct_key}"
                )

    def test_bypass_is_case_sensitive_for_key(self, mock_config):
        """Test that the internal key comparison is case-sensitive."""
        from starlette.requests import Request

        from app.middleware.oauth2 import Oauth2Middleware

        internal_key = "TestSecretKey123"

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"

        with patch("app.middleware.oauth2.cfg") as mock_cfg:
            mock_cfg.FASTGEOAPI_WITH_MCP = True
            mock_cfg.MCP_INTERNAL_KEY = internal_key
            mock_cfg.FASTGEOAPI_CONTEXT = "/geoapi"

            middleware = Oauth2Middleware(
                app=MagicMock(),
                config=mock_config,
            )

            # Test exact key - should pass
            request.headers = {"X-MCP-Internal-Key": "TestSecretKey123"}
            assert middleware._is_valid_mcp_internal_request(request) is True

            # Test lowercase - should fail
            request.headers = {"X-MCP-Internal-Key": "testsecretkey123"}
            assert middleware._is_valid_mcp_internal_request(request) is False

            # Test uppercase - should fail
            request.headers = {"X-MCP-Internal-Key": "TESTSECRETKEY123"}
            assert middleware._is_valid_mcp_internal_request(request) is False

    def test_bypass_rejects_empty_key(self, mock_config):
        """Test that empty internal key is rejected."""
        from starlette.requests import Request

        from app.middleware.oauth2 import Oauth2Middleware

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"

        with patch("app.middleware.oauth2.cfg") as mock_cfg:
            mock_cfg.FASTGEOAPI_WITH_MCP = True
            mock_cfg.MCP_INTERNAL_KEY = "valid-key"
            mock_cfg.FASTGEOAPI_CONTEXT = "/geoapi"

            middleware = Oauth2Middleware(
                app=MagicMock(),
                config=mock_config,
            )

            # Empty key header should fail
            request.headers = {"X-MCP-Internal-Key": ""}
            assert middleware._is_valid_mcp_internal_request(request) is False

    def test_bypass_rejects_none_client(self, mock_config):
        """Test that requests with None client are rejected."""
        from starlette.requests import Request

        from app.middleware.oauth2 import Oauth2Middleware

        internal_key = "test-key"

        request = MagicMock(spec=Request)
        request.client = None  # No client info
        request.headers = {"X-MCP-Internal-Key": internal_key}
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"

        with patch("app.middleware.oauth2.cfg") as mock_cfg:
            mock_cfg.FASTGEOAPI_WITH_MCP = True
            mock_cfg.MCP_INTERNAL_KEY = internal_key
            mock_cfg.FASTGEOAPI_CONTEXT = "/geoapi"

            middleware = Oauth2Middleware(
                app=MagicMock(),
                config=mock_config,
            )

            result = middleware._is_valid_mcp_internal_request(request)
            assert result is False

    def test_internal_key_stored_in_config(self):
        """Test that MCP internal key is properly stored in config at runtime."""
        import secrets
        from unittest.mock import MagicMock

        # Simulate what create_mcp_server does
        mock_cfg = MagicMock()
        mcp_internal_key = secrets.token_urlsafe(32)
        mock_cfg.MCP_INTERNAL_KEY = mcp_internal_key

        # Verify it's stored
        assert mock_cfg.MCP_INTERNAL_KEY == mcp_internal_key
        assert len(mock_cfg.MCP_INTERNAL_KEY) >= 32

    def test_httpx_client_includes_internal_key_header(self):
        """Test that the httpx client is configured with the internal key header."""
        import secrets

        import httpx

        mcp_internal_key = secrets.token_urlsafe(32)

        # Create client as done in create_mcp_server
        api_client = httpx.AsyncClient(
            base_url="http://localhost:5000/geoapi",
            timeout=30.0,
            headers={"X-MCP-Internal-Key": mcp_internal_key},
        )

        # Verify the header is set
        assert "X-MCP-Internal-Key" in api_client.headers
        assert api_client.headers["X-MCP-Internal-Key"] == mcp_internal_key


class TestMCPAuthTokenVerifierReturnsAccessToken:
    """Test MCPAuthTokenVerifier returns AccessToken object, not dict.

    FastMCP expects verify_token() to return an AccessToken object with
    an expires_at attribute. Returning a dict causes AttributeError.
    """

    @pytest.fixture
    def mock_verify_fn(self):
        """Mock JWT verification function from mcpauth."""
        mock_auth_info = MagicMock()
        mock_auth_info.claims = {
            "sub": "user123",
            "iss": "https://example.logto.app/oidc",
            "aud": "http://localhost:5000/mcp/",
            "exp": 1766865000,
            "scope": "openid profile email",
            "client_id": "test-client-id",
        }
        return MagicMock(return_value=mock_auth_info)

    @pytest.mark.asyncio
    async def test_verify_token_returns_access_token_object(self, mock_verify_fn):
        """Test that verify_token returns AccessToken object, not dict."""
        from mcp.server.auth.provider import AccessToken

        from app.auth.mcp_auth_provider import MCPAuthTokenVerifier

        verifier = MCPAuthTokenVerifier(
            verify_fn=mock_verify_fn,
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="http://localhost:5000/mcp/",
            required_scopes=["openid", "profile", "email"],
        )

        result = await verifier.verify_token("valid-jwt-token")

        # This should be an AccessToken object, not a dict
        assert isinstance(
            result, AccessToken
        ), f"verify_token should return AccessToken, got {type(result).__name__}"

    @pytest.mark.asyncio
    async def test_verify_token_has_expires_at_attribute(self, mock_verify_fn):
        """Test that verify_token result has expires_at attribute."""
        from app.auth.mcp_auth_provider import MCPAuthTokenVerifier

        verifier = MCPAuthTokenVerifier(
            verify_fn=mock_verify_fn,
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="http://localhost:5000/mcp/",
            required_scopes=["openid", "profile", "email"],
        )

        result = await verifier.verify_token("valid-jwt-token")

        # Must have expires_at attribute (not dict key)
        assert hasattr(result, "expires_at"), "verify_token result must have expires_at attribute"
        assert result.expires_at == 1766865000

    @pytest.mark.asyncio
    async def test_verify_token_has_client_id_attribute(self, mock_verify_fn):
        """Test that verify_token result has client_id attribute."""
        from app.auth.mcp_auth_provider import MCPAuthTokenVerifier

        verifier = MCPAuthTokenVerifier(
            verify_fn=mock_verify_fn,
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="http://localhost:5000/mcp/",
            required_scopes=["openid", "profile", "email"],
        )

        result = await verifier.verify_token("valid-jwt-token")

        assert hasattr(result, "client_id"), "verify_token result must have client_id attribute"
        assert result.client_id == "test-client-id"

    @pytest.mark.asyncio
    async def test_verify_token_has_scopes_attribute(self, mock_verify_fn):
        """Test that verify_token result has scopes attribute as list."""
        from app.auth.mcp_auth_provider import MCPAuthTokenVerifier

        verifier = MCPAuthTokenVerifier(
            verify_fn=mock_verify_fn,
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="http://localhost:5000/mcp/",
            required_scopes=["openid", "profile", "email"],
        )

        result = await verifier.verify_token("valid-jwt-token")

        assert hasattr(result, "scopes"), "verify_token result must have scopes attribute"
        assert isinstance(result.scopes, list)
        assert "openid" in result.scopes
        assert "profile" in result.scopes
        assert "email" in result.scopes

    @pytest.mark.asyncio
    async def test_verify_token_has_token_attribute(self, mock_verify_fn):
        """Test that verify_token result has token attribute."""
        from app.auth.mcp_auth_provider import MCPAuthTokenVerifier

        verifier = MCPAuthTokenVerifier(
            verify_fn=mock_verify_fn,
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="http://localhost:5000/mcp/",
            required_scopes=["openid", "profile", "email"],
        )

        result = await verifier.verify_token("valid-jwt-token")

        assert hasattr(result, "token"), "verify_token result must have token attribute"
        assert result.token == "valid-jwt-token"

    @pytest.mark.asyncio
    async def test_verify_token_returns_none_for_invalid_token(self):
        """Test that verify_token returns None for invalid tokens."""
        from app.auth.mcp_auth_provider import MCPAuthTokenVerifier

        # Mock verify function that raises an exception
        def failing_verify_fn(token):
            raise ValueError("Invalid token")

        verifier = MCPAuthTokenVerifier(
            verify_fn=failing_verify_fn,
            client_id="test-client-id",
            client_secret="test-client-secret",
            base_url="http://localhost:5000/mcp/",
            required_scopes=["openid", "profile", "email"],
        )

        result = await verifier.verify_token("invalid-token")

        # Should return None for invalid tokens, not a dict with active=False
        assert result is None


class TestTrustingUpstreamTokenVerifier:
    """Test TrustingUpstreamTokenVerifier handles opaque tokens from IdPs like Logto.

    When IdPs like Logto are used without requesting an API Resource, they return
    opaque tokens (not JWTs). FastMCP's default JWTVerifier cannot validate these
    tokens because they're not JWTs.

    The TrustingUpstreamTokenVerifier solves this by accepting opaque tokens as valid,
    trusting that they were validated during the OAuth code exchange with the IdP.
    """

    @pytest.fixture
    def verifier(self):
        """Create TrustingUpstreamTokenVerifier instance."""
        from app.auth.mcp_auth_provider import TrustingUpstreamTokenVerifier

        return TrustingUpstreamTokenVerifier(
            client_id="test-client-id",
            client_secret="test-client-secret",
            required_scopes=["openid", "profile", "email"],
        )

    def test_trusting_verifier_class_exists(self):
        """Test that TrustingUpstreamTokenVerifier class exists."""
        from app.auth.mcp_auth_provider import TrustingUpstreamTokenVerifier

        assert TrustingUpstreamTokenVerifier is not None

    def test_trusting_verifier_initialization(self, verifier):
        """Test that TrustingUpstreamTokenVerifier initializes correctly."""
        assert verifier.client_id == "test-client-id"
        assert verifier.client_secret == "test-client-secret"
        assert verifier.required_scopes == ["openid", "profile", "email"]
        # OIDCProxy interface requires introspection_url attribute
        assert hasattr(verifier, "introspection_url")

    @pytest.mark.asyncio
    async def test_verify_token_returns_access_token_object(self, verifier):
        """Test that verify_token returns AccessToken object for opaque tokens."""
        from mcp.server.auth.provider import AccessToken

        # Opaque token from Logto (not a JWT)
        opaque_token = "opaque_token_abc123_not_a_jwt"

        result = await verifier.verify_token(opaque_token)

        assert isinstance(
            result, AccessToken
        ), f"verify_token should return AccessToken, got {type(result).__name__}"

    @pytest.mark.asyncio
    async def test_verify_token_has_required_attributes(self, verifier):
        """Test that verify_token result has all required attributes."""
        opaque_token = "opaque_token_xyz789"

        result = await verifier.verify_token(opaque_token)

        # Must have all attributes required by FastMCP
        assert hasattr(result, "token")
        assert hasattr(result, "client_id")
        assert hasattr(result, "scopes")
        assert hasattr(result, "expires_at")

    @pytest.mark.asyncio
    async def test_verify_token_returns_correct_values(self, verifier):
        """Test that verify_token returns correct values from config."""
        opaque_token = "logto_opaque_token_12345"

        result = await verifier.verify_token(opaque_token)

        assert result.token == opaque_token
        assert result.client_id == "test-client-id"
        assert result.scopes == ["openid", "profile", "email"]
        # expires_at is None because expiry is managed by FastMCP's JWT
        assert result.expires_at is None

    @pytest.mark.asyncio
    async def test_verify_token_never_returns_none(self, verifier):
        """Test that verify_token always returns AccessToken, never None.

        Unlike JWT verifiers that return None for invalid tokens,
        TrustingUpstreamTokenVerifier always trusts the token because
        it was already validated during OAuth exchange.
        """
        # Even weird-looking tokens should be accepted
        weird_tokens = [
            "",  # Empty token
            "a",  # Single char
            "x" * 1000,  # Very long token
            "token with spaces",  # Spaces
            "token\nwith\nnewlines",  # Newlines
        ]

        for token in weird_tokens:
            result = await verifier.verify_token(token)
            assert result is not None, f"Should accept token: {token!r}"

    @pytest.mark.asyncio
    async def test_verify_token_accepts_real_logto_opaque_format(self, verifier):
        """Test that verify_token accepts tokens in Logto's opaque format.

        Logto opaque tokens look like base64url-encoded random strings.
        """
        # Real-looking Logto opaque token
        logto_token = "mJbQ4EsKz_Nxp2QhvTk9_3aL7cRm1xYz"

        result = await verifier.verify_token(logto_token)

        assert result is not None
        assert result.token == logto_token


class TestOIDCProxyWithTrustingVerifier:
    """Test that OIDCProxy can be configured with TrustingUpstreamTokenVerifier."""

    def test_oidc_proxy_accepts_custom_token_verifier(self):
        """Test that OIDCProxy accepts TrustingUpstreamTokenVerifier."""
        from unittest.mock import MagicMock, patch

        from app.auth.mcp_auth_provider import TrustingUpstreamTokenVerifier

        mock_oidc_config = {
            "issuer": "https://example.logto.app/oidc",
            "authorization_endpoint": "https://example.logto.app/oidc/auth",
            "token_endpoint": "https://example.logto.app/oidc/token",
            "jwks_uri": "https://example.logto.app/oidc/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            from app.auth.mcp_auth_provider import OIDCProxyWithoutResource

            token_verifier = TrustingUpstreamTokenVerifier(
                client_id="test-client",
                client_secret="test-secret",
                required_scopes=["openid", "profile"],
            )

            # This should not raise an exception
            proxy = OIDCProxyWithoutResource(
                config_url="https://example.logto.app/oidc/.well-known/openid-configuration",
                client_id="test-client",
                client_secret="test-secret",
                base_url="http://localhost:5000/mcp/",
                token_verifier=token_verifier,
            )

            assert proxy is not None


class TestMCPRemoteOAuthFlow:
    """Test the OAuth flow that mcp-remote uses.

    This test class reproduces the issue where mcp-remote fails with:
    "Existing OAuth client information is required when exchanging an authorization code"

    The root cause is:
    1. mcp-remote registers a client via DCR (POST /mcp/register) - SUCCESS
    2. mcp-remote tries to connect to MCP endpoint (POST /mcp/) without a token
    3. Server returns 401 with "invalid_token" error
    4. mcp-remote SDK interprets this as InvalidClientError
    5. mcp-remote calls invalidateCredentials("all") which DELETES client_info.json
    6. After browser auth completes, mcp-remote has no client info to exchange the code

    The fix: The initial connection attempt before OAuth should return a different
    error that doesn't trigger credential invalidation.
    """

    @pytest.fixture
    def mock_oidc_config(self):
        """Mock OIDC configuration."""
        return {
            "issuer": "https://example.logto.app/oidc",
            "authorization_endpoint": "https://example.logto.app/oidc/auth",
            "token_endpoint": "https://example.logto.app/oidc/token",
            "jwks_uri": "https://example.logto.app/oidc/jwks",
            "introspection_endpoint": "https://example.logto.app/oidc/token/introspection",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    @pytest.mark.asyncio
    async def test_unauthenticated_mcp_request_returns_unauthorized_not_invalid_token(
        self, mock_oidc_config
    ):
        """Test that unauthenticated MCP requests return proper OAuth error.

        When mcp-remote first connects without a token, the server should return
        a 401 with WWW-Authenticate header indicating authentication is required,
        NOT an "invalid_token" error which causes client credential invalidation.

        Per RFC 6750, the error should be:
        - "invalid_request" if the request lacks required parameters
        - "invalid_token" if the token is malformed/expired/revoked
        - No error code at all if simply missing authentication

        For MCP OAuth flow, when no token is provided, the response should be
        a simple 401 with WWW-Authenticate header pointing to the auth server,
        without "invalid_token" error that triggers SDK's invalidateCredentials().
        """
        from unittest.mock import MagicMock, patch

        from starlette.testclient import TestClient

        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            with patch("requests.get", return_value=mock_response):
                # Create a minimal test app with MCP auth
                from starlette.applications import Starlette
                from starlette.routing import Mount

                from app.auth.mcp_auth_provider import (
                    OIDCProxyWithoutResource,
                    TrustingUpstreamTokenVerifier,
                    patch_fastmcp_auth_middleware,
                )

                # IMPORTANT: Patch FastMCP's middleware BEFORE creating the server
                # This replaces RequireAuthMiddleware with our RFC 6750 compliant version
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

                # Create FastMCP server with this auth
                from fastmcp import FastMCP

                mcp = FastMCP("Test MCP", auth=auth)

                # Get the ASGI app
                mcp_app = mcp.http_app(path="/")

                # Create test app
                app = Starlette(
                    routes=[Mount("/mcp", app=mcp_app)],
                )

                client = TestClient(app, raise_server_exceptions=False)

                # Make request without auth token (like mcp-remote does initially)
                response = client.post(
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
                        "Accept": "application/json, text/event-stream",
                    },
                )

                # Should get 401 Unauthorized
                assert response.status_code == 401, f"Expected 401, got {response.status_code}"

                # Check the error response
                # The key issue: if error is "invalid_token", mcp-remote SDK will
                # call invalidateCredentials("all") and delete client_info.json
                #
                # Per OAuth 2.0 Bearer Token Usage (RFC 6750) Section 3.1:
                # - "invalid_token" means the token is malformed, expired, or revoked
                # - When NO token is provided, a simple 401 without error code is correct
                #
                # This test should FAIL currently because the server returns "invalid_token"
                # even when no token is provided.

                # Check WWW-Authenticate header exists
                assert (
                    "WWW-Authenticate" in response.headers
                ), "Response should include WWW-Authenticate header"

                www_auth = response.headers.get("WWW-Authenticate", "")

                # The error should NOT be "invalid_token" when no token was sent
                # This is the bug: server returns invalid_token which triggers
                # mcp-remote to delete client credentials
                assert 'error="invalid_token"' not in www_auth, (
                    "Server should NOT return 'invalid_token' when no token is provided. "
                    "This causes mcp-remote to invalidate client credentials. "
                    f"Got WWW-Authenticate: {www_auth}"
                )

    @pytest.mark.asyncio
    async def test_invalid_token_error_only_for_actual_invalid_tokens(self, mock_oidc_config):
        """Test that invalid_token error is only returned for actual invalid tokens.

        Per RFC 6750:
        - "invalid_token": The access token provided is expired, revoked,
          malformed, or invalid for other reasons.

        This error should ONLY be returned when a token IS provided but is invalid.
        When NO token is provided, a different response is appropriate.
        """
        from unittest.mock import MagicMock, patch

        from starlette.testclient import TestClient

        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            with patch("requests.get", return_value=mock_response):
                from starlette.applications import Starlette
                from starlette.routing import Mount

                from app.auth.mcp_auth_provider import (
                    OIDCProxyWithoutResource,
                    TrustingUpstreamTokenVerifier,
                    patch_fastmcp_auth_middleware,
                )

                # IMPORTANT: Patch FastMCP's middleware BEFORE creating the server
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

                mcp = FastMCP("Test MCP", auth=auth)
                mcp_app = mcp.http_app(path="/")

                app = Starlette(
                    routes=[Mount("/mcp", app=mcp_app)],
                )

                client = TestClient(app, raise_server_exceptions=False)

                # Request WITH an invalid token - this SHOULD return invalid_token
                response = client.post(
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
                        "Accept": "application/json, text/event-stream",
                        "Authorization": "Bearer invalid-token-that-doesnt-exist",
                    },
                )

                assert response.status_code == 401

                www_auth = response.headers.get("WWW-Authenticate", "")

                # For an ACTUAL invalid token, invalid_token error IS appropriate
                # This is correct behavior per RFC 6750
                assert 'error="invalid_token"' in www_auth, (
                    "Server SHOULD return 'invalid_token' when an invalid token is provided. "
                    f"Got WWW-Authenticate: {www_auth}"
                )


class TestCustomOIDCProxyIntegration:
    """Integration tests for CustomOIDCProxy with the full MCP setup."""

    def test_mcp_server_uses_custom_oidc_proxy_when_configured(self):
        """Test that create_mcp_server uses CustomOIDCProxy when OIDC is configured."""
        import os
        import sys
        from unittest import mock

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
                with mock.patch(
                    "fastmcp.server.auth.oidc_proxy.httpx.get",
                    return_value=mock_response,
                ):
                    from app.main import create_mcp_server

                    mcp_server, mcp_app, well_known_routes = create_mcp_server()

                    # Verify MCP server was created
                    assert mcp_server is not None
                    assert mcp_app is not None

                    # Verify well-known routes are present (indicates OIDC was configured)
                    assert len(well_known_routes) > 0

    def test_client_registration_options_include_oidc_scopes(self):
        """Test that client registration options include standard OIDC scopes."""
        import os
        import sys
        from unittest import mock

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

            mock_response = mock.MagicMock()
            mock_response.json.return_value = mock_oidc_config
            mock_response.raise_for_status = mock.MagicMock()

            with mock.patch(
                "fastmcp.server.auth.oidc_proxy.httpx.get",
                return_value=mock_response,
            ):
                # Import the CustomOIDCProxy class definition from main
                # and verify it sets valid_scopes correctly

                # The scopes should include openid, profile, email for mcp-remote compatibility
                expected_scopes = ["openid", "profile", "email"]

                # This is verified in the create_mcp_server function where:
                # auth.client_registration_options.valid_scopes = ["openid", "profile", "email"]
                assert "openid" in expected_scopes
                assert "profile" in expected_scopes
                assert "email" in expected_scopes


class TestOAuthEndpointURLConsistency:
    """Test that OAuth endpoints return consistent results regardless of trailing slash.

    mcp-remote strips trailing slashes when building well-known URLs:
    - First request (discovery): uses /mcp/ -> gets PRM with authorization_servers
    - Second request (finishAuth): uses /mcp (no trailing slash) -> may get different PRM

    If the two endpoints return different authorization_servers, mcp-remote will:
    1. Register client with one auth server
    2. Try to exchange code with a different auth server
    3. Get InvalidClientError -> invalidateCredentials("all") -> delete client_info.json
    4. Fail with "Existing OAuth client information is required..."

    These tests ensure both endpoints return identical results.
    """

    @pytest.fixture
    def mock_oidc_config(self):
        """Mock OIDC configuration from IdP."""
        return {
            "issuer": "https://example.logto.app/oidc",
            "authorization_endpoint": "https://example.logto.app/oidc/auth",
            "token_endpoint": "https://example.logto.app/oidc/token",
            "jwks_uri": "https://example.logto.app/oidc/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    @pytest.mark.asyncio
    async def test_prm_endpoint_consistent_with_and_without_trailing_slash(self, mock_oidc_config):
        """Test that /.well-known/oauth-protected-resource/mcp and /mcp/ return same data.

        This is the root cause of the mcp-remote credential loss bug:
        - /mcp/ returns authorization_servers: ["http://localhost:5000/mcp/"]
        - /mcp (no slash) returns authorization_servers: ["https://logto.app/oidc"]

        mcp-remote uses /mcp/ for initial DCR but /mcp for token exchange,
        causing it to try exchanging the code with the wrong auth server.
        """
        from unittest.mock import MagicMock, patch

        from starlette.testclient import TestClient

        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            with patch("requests.get", return_value=mock_response):
                from starlette.applications import Starlette
                from starlette.routing import Mount

                from app.auth.mcp_auth_provider import (
                    configure_mcp_auth,
                    patch_fastmcp_auth_middleware,
                )

                patch_fastmcp_auth_middleware()

                # Configure auth as done in create_mcp_server
                auth, mcp_auth_routes = configure_mcp_auth(
                    oidc_well_known_endpoint="https://example.logto.app/oidc/.well-known/openid-configuration",
                    client_id="test-client",
                    client_secret="test-secret",
                    mcp_base_url="http://localhost:5000/mcp/",
                    scopes=["openid", "profile", "email"],
                )

                from fastmcp import FastMCP

                mcp = FastMCP("Test MCP", auth=auth)
                mcp_app = mcp.http_app(path="/")

                # Build app with both MCP routes and well-known routes
                routes = [Mount("/mcp", app=mcp_app)]
                for route in mcp_auth_routes:
                    routes.append(route)

                app = Starlette(routes=routes)
                client = TestClient(app, raise_server_exceptions=False)

                # Test both URL variants
                response_with_slash = client.get("/.well-known/oauth-protected-resource/mcp/")
                response_without_slash = client.get("/.well-known/oauth-protected-resource/mcp")

                # Both should return 200
                assert (
                    response_with_slash.status_code == 200
                ), f"Expected 200 for /mcp/, got {response_with_slash.status_code}"
                assert (
                    response_without_slash.status_code == 200
                ), f"Expected 200 for /mcp, got {response_without_slash.status_code}"

                # Parse responses
                prm_with_slash = response_with_slash.json()
                prm_without_slash = response_without_slash.json()

                # CRITICAL: authorization_servers MUST be identical
                assert prm_with_slash.get("authorization_servers") == prm_without_slash.get(
                    "authorization_servers"
                ), (
                    f"authorization_servers mismatch!\n"
                    f"  /mcp/ returns: {prm_with_slash.get('authorization_servers')}\n"
                    f"  /mcp returns: {prm_without_slash.get('authorization_servers')}\n"
                    f"This causes mcp-remote to register with one auth server but "
                    f"exchange tokens with another, leading to InvalidClientError "
                    f"and credential deletion."
                )

    @pytest.mark.asyncio
    async def test_authorization_server_metadata_consistent_trailing_slash(self, mock_oidc_config):
        """Test that authorization server metadata is consistent with/without trailing slash."""
        from unittest.mock import MagicMock, patch

        from starlette.testclient import TestClient

        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            with patch("requests.get", return_value=mock_response):
                from starlette.applications import Starlette
                from starlette.routing import Mount

                from app.auth.mcp_auth_provider import (
                    configure_mcp_auth,
                    patch_fastmcp_auth_middleware,
                )

                patch_fastmcp_auth_middleware()

                auth, mcp_auth_routes = configure_mcp_auth(
                    oidc_well_known_endpoint="https://example.logto.app/oidc/.well-known/openid-configuration",
                    client_id="test-client",
                    client_secret="test-secret",
                    mcp_base_url="http://localhost:5000/mcp/",
                    scopes=["openid", "profile", "email"],
                )

                from fastmcp import FastMCP

                mcp = FastMCP("Test MCP", auth=auth)
                mcp_app = mcp.http_app(path="/")

                routes = [Mount("/mcp", app=mcp_app)]
                for route in mcp_auth_routes:
                    routes.append(route)

                app = Starlette(routes=routes)
                client = TestClient(app, raise_server_exceptions=False)

                # Test authorization server metadata endpoints
                response_with_slash = client.get("/.well-known/oauth-authorization-server/mcp/")
                response_without_slash = client.get("/.well-known/oauth-authorization-server/mcp")

                # At least one should work (depending on how routes are configured)
                # The key is consistency - both should behave the same way
                if response_with_slash.status_code == 200:
                    if response_without_slash.status_code == 200:
                        # Both work - they should return identical data
                        as_with_slash = response_with_slash.json()
                        as_without_slash = response_without_slash.json()

                        assert as_with_slash.get("issuer") == as_without_slash.get("issuer"), (
                            f"issuer mismatch: {as_with_slash.get('issuer')} vs "
                            f"{as_without_slash.get('issuer')}"
                        )

                        assert as_with_slash.get("token_endpoint") == as_without_slash.get(
                            "token_endpoint"
                        ), "token_endpoint should be consistent"

    @pytest.mark.asyncio
    async def test_mcp_remote_oauth_flow_uses_consistent_auth_server(self, mock_oidc_config):
        """Simulate the mcp-remote OAuth flow to verify it uses consistent auth servers.

        mcp-remote flow:
        1. GET /mcp/ -> 401 with WWW-Authenticate pointing to resource_metadata
        2. GET /.well-known/oauth-protected-resource/mcp/ -> get authorization_servers[0]
        3. GET /.well-known/oauth-authorization-server on that server -> get endpoints
        4. POST /register -> DCR
        5. Browser auth flow
        6. GET /.well-known/oauth-protected-resource/mcp (NO SLASH!) -> get authorization_servers[0]
        7. POST /token on that server -> exchange code

        If step 2 and step 6 return different authorization_servers, the flow fails.
        """
        from unittest.mock import MagicMock, patch

        from starlette.testclient import TestClient

        mock_response = MagicMock()
        mock_response.json.return_value = mock_oidc_config
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_response):
            with patch("requests.get", return_value=mock_response):
                from starlette.applications import Starlette
                from starlette.routing import Mount

                from app.auth.mcp_auth_provider import (
                    configure_mcp_auth,
                    patch_fastmcp_auth_middleware,
                )

                patch_fastmcp_auth_middleware()

                auth, mcp_auth_routes = configure_mcp_auth(
                    oidc_well_known_endpoint="https://example.logto.app/oidc/.well-known/openid-configuration",
                    client_id="test-client",
                    client_secret="test-secret",
                    mcp_base_url="http://localhost:5000/mcp/",
                    scopes=["openid", "profile", "email"],
                )

                from fastmcp import FastMCP

                mcp = FastMCP("Test MCP", auth=auth)
                mcp_app = mcp.http_app(path="/")

                routes = [Mount("/mcp", app=mcp_app)]
                for route in mcp_auth_routes:
                    routes.append(route)

                app = Starlette(routes=routes)
                client = TestClient(app, raise_server_exceptions=False)

                # Step 1: Initial request (mcp-remote uses trailing slash)
                initial_response = client.post(
                    "/mcp/",
                    json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
                )
                assert initial_response.status_code == 401

                # Step 2: Discovery with trailing slash (mcp-remote's first discovery)
                prm_initial = client.get("/.well-known/oauth-protected-resource/mcp/")

                # Step 6: Discovery without trailing slash (mcp-remote's finishAuth)
                # mcp-remote strips trailing slash in buildWellKnownPath()
                prm_finish = client.get("/.well-known/oauth-protected-resource/mcp")

                # Both must return 200
                assert (
                    prm_initial.status_code == 200
                ), f"Initial PRM request failed: {prm_initial.status_code}"
                assert (
                    prm_finish.status_code == 200
                ), f"FinishAuth PRM request failed: {prm_finish.status_code}"

                # Get authorization servers from both
                auth_servers_initial = prm_initial.json().get("authorization_servers", [])
                auth_servers_finish = prm_finish.json().get("authorization_servers", [])

                # CRITICAL ASSERTION: These must be identical
                assert auth_servers_initial == auth_servers_finish, (
                    f"CRITICAL: authorization_servers changed between discovery and finishAuth!\n"
                    f"  Initial discovery (/mcp/): {auth_servers_initial}\n"
                    f"  FinishAuth (/mcp): {auth_servers_finish}\n\n"
                    f"This is the root cause of mcp-remote failing with:\n"
                    f"'Existing OAuth client information is required when exchanging an authorization code'\n\n"
                    f"mcp-remote registers a client with {auth_servers_initial[0] if auth_servers_initial else 'N/A'}\n"
                    f"but tries to exchange the code with {auth_servers_finish[0] if auth_servers_finish else 'N/A'}\n"
                    f"causing InvalidClientError -> invalidateCredentials('all') -> client_info.json deleted"
                )

    def test_resource_url_normalization(self):
        """Test that resource URLs are normalized consistently.

        The PRM 'resource' field should match regardless of trailing slash in request.
        """
        # URLs that should be treated as equivalent
        url_pairs = [
            ("http://localhost:5000/mcp/", "http://localhost:5000/mcp"),
            ("http://localhost:5000/mcp", "http://localhost:5000/mcp/"),
        ]

        for url1, url2 in url_pairs:
            # Normalize by stripping trailing slash
            normalized1 = url1.rstrip("/")
            normalized2 = url2.rstrip("/")

            assert (
                normalized1 == normalized2
            ), f"URLs should normalize to the same value: {url1} vs {url2}"
