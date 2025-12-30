"""Test MCP internal authentication bypass.

These tests verify that:
1. Internal MCP requests with valid key bypass auth (regardless of source IP)
2. Requests without the internal key require auth
3. Requests with wrong internal key require auth
4. Bypass only works when FASTGEOAPI_WITH_MCP is enabled
5. The internal key provides sufficient security through cryptographic strength

Security Model:
- The internal key is generated using secrets.token_urlsafe(32) providing 256 bits of entropy
- The key is generated at runtime and never exposed externally
- An attacker cannot brute-force a 256-bit key in any reasonable timeframe
- This approach is necessary for containerized deployments where internal requests
  may not originate from localhost due to container networking
"""

import secrets
from unittest.mock import MagicMock, patch

import pytest
from starlette.requests import Request

from app.config.app import configuration as cfg
from app.middleware.oauth2 import Oauth2Middleware


class TestMCPInternalAuthBypass:
    """Test cases for MCP internal authentication bypass."""

    @pytest.fixture
    def mock_config(self):
        """Create mock OAuth2 config."""
        config = MagicMock()
        config.authentication = []
        return config

    @pytest.fixture
    def mock_request_localhost(self):
        """Create mock request from localhost."""
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {}
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"
        return request

    @pytest.fixture
    def mock_request_external(self):
        """Create mock request from external IP."""
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "192.168.1.100"
        request.headers = {}
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"
        return request

    def test_bypass_with_valid_key_from_localhost_mcp_enabled(
        self, mock_config, mock_request_localhost
    ):
        """Test: bypass auth when MCP enabled, localhost, valid key."""
        internal_key = "test-secret-key-12345"
        mock_request_localhost.headers = {"X-MCP-Internal-Key": internal_key}

        # Use patch.object to patch specific attributes on the singleton
        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(mock_request_localhost)
                assert result is True

    def test_no_bypass_when_mcp_disabled(self, mock_config, mock_request_localhost):
        """Test: require auth when FASTGEOAPI_WITH_MCP is False."""
        internal_key = "test-secret-key-12345"
        mock_request_localhost.headers = {"X-MCP-Internal-Key": internal_key}

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", False):
            with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(mock_request_localhost)
                assert result is False

    def test_no_bypass_without_internal_key_header(self, mock_config, mock_request_localhost):
        """Test: require auth when X-MCP-Internal-Key header is missing."""
        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", "test-secret-key-12345"):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                # No header set
                mock_request_localhost.headers = {}
                result = middleware._is_valid_mcp_internal_request(mock_request_localhost)
                assert result is False

    def test_no_bypass_with_wrong_internal_key(self, mock_config, mock_request_localhost):
        """Test: require auth when X-MCP-Internal-Key doesn't match."""
        mock_request_localhost.headers = {"X-MCP-Internal-Key": "wrong-key"}

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", "correct-key"):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(mock_request_localhost)
                assert result is False

    def test_bypass_from_external_ip_with_valid_key(self, mock_config, mock_request_external):
        """Test: bypass auth when request comes from external IP with valid key.

        Since Solution 1, we rely solely on the secret key (256-bit entropy)
        without IP restrictions, as container networking may route internal
        requests through external IPs.
        """
        internal_key = "test-secret-key-12345"
        mock_request_external.headers = {"X-MCP-Internal-Key": internal_key}

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(mock_request_external)
                assert result is True

    def test_no_bypass_when_mcp_internal_key_not_configured(
        self, mock_config, mock_request_localhost
    ):
        """Test: require auth when MCP_INTERNAL_KEY is not set in config."""
        mock_request_localhost.headers = {"X-MCP-Internal-Key": "some-key"}

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", None):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(mock_request_localhost)
                assert result is False

    def test_bypass_from_ipv6_localhost(self, mock_config):
        """Test: bypass auth when request comes from ::1 (IPv6 localhost)."""
        internal_key = "test-secret-key-12345"

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "::1"
        request.headers = {"X-MCP-Internal-Key": internal_key}
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(request)
                assert result is True

    def test_bypass_from_localhost_hostname(self, mock_config):
        """Test: bypass auth when request comes from 'localhost' hostname."""
        internal_key = "test-secret-key-12345"

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "localhost"
        request.headers = {"X-MCP-Internal-Key": internal_key}
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(request)
                assert result is True


class TestMCPKeyOnlyAuthBypass:
    """Test cases for key-only MCP authentication bypass (Solution 1).

    These tests validate the security of bypassing auth based solely on
    the X-MCP-Internal-Key header, without IP restrictions.
    """

    @pytest.fixture
    def mock_config(self):
        """Create mock OAuth2 config."""
        config = MagicMock()
        config.authentication = []
        return config

    def _create_request(self, client_host: str, internal_key: str | None = None):
        """Helper to create mock request with given host and optional key."""
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = client_host
        request.headers = {"X-MCP-Internal-Key": internal_key} if internal_key else {}
        request.method = "GET"
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"
        return request

    def test_bypass_from_external_ip_with_valid_key(self, mock_config):
        """Test: bypass auth from external IP when valid key is provided.

        This is the core test for Solution 1 - container deployments where
        internal requests don't come from localhost.
        """
        internal_key = secrets.token_urlsafe(32)
        external_ip = "66.241.124.133"  # Real external IP from fly.io

        request = self._create_request(external_ip, internal_key)

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                middleware = Oauth2Middleware(app=MagicMock(), config=mock_config)
                result = middleware._is_valid_mcp_internal_request(request)
                assert result is True

    def test_bypass_from_container_private_ip_with_valid_key(self, mock_config):
        """Test: bypass auth from container private IP with valid key."""
        internal_key = secrets.token_urlsafe(32)
        private_ips = ["172.19.0.5", "10.0.0.15", "192.168.1.100"]

        for ip in private_ips:
            request = self._create_request(ip, internal_key)

            with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
                with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                    middleware = Oauth2Middleware(app=MagicMock(), config=mock_config)
                    result = middleware._is_valid_mcp_internal_request(request)
                    assert result is True, f"Should bypass for IP {ip}"

    def test_no_bypass_from_any_ip_without_key(self, mock_config):
        """Test: require auth from any IP when key is missing."""
        internal_key = secrets.token_urlsafe(32)
        test_ips = [
            "127.0.0.1",
            "::1",
            "localhost",
            "66.241.124.133",
            "172.19.0.5",
        ]

        for ip in test_ips:
            request = self._create_request(ip, internal_key=None)

            with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
                with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                    middleware = Oauth2Middleware(app=MagicMock(), config=mock_config)
                    result = middleware._is_valid_mcp_internal_request(request)
                    assert result is False, f"Should NOT bypass for IP {ip} without key"

    def test_no_bypass_with_wrong_key_from_any_ip(self, mock_config):
        """Test: require auth when wrong key is provided from any IP."""
        correct_key = secrets.token_urlsafe(32)
        wrong_key = secrets.token_urlsafe(32)
        test_ips = ["127.0.0.1", "::1", "66.241.124.133", "172.19.0.5"]

        for ip in test_ips:
            request = self._create_request(ip, wrong_key)

            with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
                with patch.object(cfg, "MCP_INTERNAL_KEY", correct_key):
                    middleware = Oauth2Middleware(app=MagicMock(), config=mock_config)
                    result = middleware._is_valid_mcp_internal_request(request)
                    assert result is False, f"Should NOT bypass for IP {ip} with wrong key"


class TestMCPKeySecurityProperties:
    """Test the cryptographic security properties of the internal key."""

    def test_key_has_sufficient_entropy(self):
        """Test: generated key has at least 256 bits of entropy.

        secrets.token_urlsafe(32) generates 32 bytes = 256 bits of entropy.
        This is computationally infeasible to brute-force.
        """
        key = secrets.token_urlsafe(32)
        # URL-safe base64 encoding: each character represents ~6 bits
        # 32 bytes = 256 bits, encoded as ~43 characters
        assert len(key) >= 42, "Key should be at least 42 characters (256 bits)"

    def test_keys_are_unique(self):
        """Test: each generated key is unique."""
        keys = [secrets.token_urlsafe(32) for _ in range(1000)]
        unique_keys = set(keys)
        assert len(unique_keys) == 1000, "All generated keys should be unique"

    def test_key_is_unpredictable(self):
        """Test: keys don't follow predictable patterns.

        This is a basic statistical test - keys should be uniformly distributed.
        """
        keys = [secrets.token_urlsafe(32) for _ in range(100)]

        # Check that first characters are varied (not always the same)
        first_chars = {k[0] for k in keys}
        assert len(first_chars) > 10, "First characters should be varied"

        # Check that keys don't share common prefixes
        prefixes_5 = {k[:5] for k in keys}
        assert len(prefixes_5) == 100, "5-char prefixes should all be unique"

    def test_empty_key_rejected(self):
        """Test: empty string key is rejected."""
        config = MagicMock()
        config.authentication = []

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"X-MCP-Internal-Key": ""}
        request.url = MagicMock()
        request.url.path = "/geoapi/test"

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", "valid-key"):
                middleware = Oauth2Middleware(app=MagicMock(), config=config)
                result = middleware._is_valid_mcp_internal_request(request)
                assert result is False

    def test_partial_key_rejected(self):
        """Test: partial key match is rejected (no substring matching)."""
        config = MagicMock()
        config.authentication = []
        full_key = "abcdefghijklmnopqrstuvwxyz123456"
        partial_key = "abcdefghijklmnop"  # First half

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"X-MCP-Internal-Key": partial_key}
        request.url = MagicMock()
        request.url.path = "/geoapi/test"

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", full_key):
                middleware = Oauth2Middleware(app=MagicMock(), config=config)
                result = middleware._is_valid_mcp_internal_request(request)
                assert result is False

    def test_key_comparison_is_case_sensitive(self):
        """Test: key comparison is case-sensitive."""
        config = MagicMock()
        config.authentication = []
        correct_key = "AbCdEfGhIjKlMnOp"

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "127.0.0.1"
        request.headers = {"X-MCP-Internal-Key": correct_key.lower()}
        request.url = MagicMock()
        request.url.path = "/geoapi/test"

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", correct_key):
                middleware = Oauth2Middleware(app=MagicMock(), config=config)
                result = middleware._is_valid_mcp_internal_request(request)
                assert result is False

    def test_key_with_extra_whitespace_rejected(self):
        """Test: key with leading/trailing whitespace is rejected."""
        config = MagicMock()
        config.authentication = []
        correct_key = "valid-internal-key"

        for padded_key in [
            f" {correct_key}",
            f"{correct_key} ",
            f" {correct_key} ",
        ]:
            request = MagicMock(spec=Request)
            request.client = MagicMock()
            request.client.host = "127.0.0.1"
            request.headers = {"X-MCP-Internal-Key": padded_key}
            request.url = MagicMock()
            request.url.path = "/geoapi/test"

            with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
                with patch.object(cfg, "MCP_INTERNAL_KEY", correct_key):
                    middleware = Oauth2Middleware(app=MagicMock(), config=config)
                    result = middleware._is_valid_mcp_internal_request(request)
                    assert result is False, f"Should reject key with whitespace: '{padded_key}'"


class TestMCPBypassDoesNotAffectNormalAuth:
    """Test that MCP bypass doesn't interfere with normal authentication."""

    @pytest.fixture
    def mock_config(self):
        """Create mock OAuth2 config."""
        config = MagicMock()
        config.authentication = []
        return config

    def test_normal_request_without_mcp_header_requires_auth(self, mock_config):
        """Test: normal requests without X-MCP-Internal-Key still require auth."""
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "203.0.113.50"  # External IP
        request.headers = {"Authorization": "Bearer some-token"}  # Normal auth header
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", "internal-key"):
                middleware = Oauth2Middleware(app=MagicMock(), config=mock_config)
                result = middleware._is_valid_mcp_internal_request(request)
                # Should return False - this request should go through normal auth
                assert result is False

    def test_request_with_both_headers_uses_mcp_bypass(self, mock_config):
        """Test: request with both MCP key and Bearer token uses MCP bypass."""
        internal_key = secrets.token_urlsafe(32)

        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = "172.19.0.5"
        request.headers = {
            "Authorization": "Bearer some-token",
            "X-MCP-Internal-Key": internal_key,
        }
        request.url = MagicMock()
        request.url.path = "/geoapi/collections"

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                middleware = Oauth2Middleware(app=MagicMock(), config=mock_config)
                result = middleware._is_valid_mcp_internal_request(request)
                # MCP bypass should take precedence
                assert result is True
