"""Test MCP internal authentication bypass.

These tests verify that:
1. Internal MCP requests (with valid key, from localhost) bypass auth
2. External requests still require authentication
3. Requests without the internal key require auth
4. Requests with wrong internal key require auth
5. Bypass only works when FASTGEOAPI_WITH_MCP is enabled
"""

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

    def test_no_bypass_from_external_ip(self, mock_config, mock_request_external):
        """Test: require auth when request comes from external IP."""
        internal_key = "test-secret-key-12345"
        mock_request_external.headers = {"X-MCP-Internal-Key": internal_key}

        with patch.object(cfg, "FASTGEOAPI_WITH_MCP", True):
            with patch.object(cfg, "MCP_INTERNAL_KEY", internal_key):
                middleware = Oauth2Middleware(
                    app=MagicMock(),
                    config=mock_config,
                )

                result = middleware._is_valid_mcp_internal_request(mock_request_external)
                assert result is False

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
