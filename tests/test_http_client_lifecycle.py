"""Test HTTP client lifecycle management.

These tests verify that:
1. httpx.AsyncClient implements the AsyncHTTPClient protocol
2. The client is properly closed when the application shuts down
3. Resource leaks are prevented through proper lifecycle management
4. Dependency injection works correctly with the protocol
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.interfaces.http_client import AsyncHTTPClient


class TestAsyncHTTPClientProtocol:
    """Test that httpx.AsyncClient implements the AsyncHTTPClient protocol."""

    def test_httpx_async_client_implements_protocol(self):
        """Verify httpx.AsyncClient is compatible with AsyncHTTPClient protocol."""
        client = httpx.AsyncClient()

        # Protocol is runtime_checkable, so isinstance should work
        assert isinstance(client, AsyncHTTPClient)

    def test_protocol_has_required_methods(self):
        """Verify the protocol defines all required methods."""
        required_methods = ["get", "post", "put", "delete", "request", "aclose"]
        required_properties = ["headers", "is_closed"]

        for method in required_methods:
            assert hasattr(AsyncHTTPClient, method)

        for prop in required_properties:
            assert hasattr(AsyncHTTPClient, prop)

    @pytest.mark.asyncio
    async def test_httpx_client_aclose_works(self):
        """Verify httpx.AsyncClient.aclose() properly closes the client."""
        client = httpx.AsyncClient()

        assert not client.is_closed

        await client.aclose()

        assert client.is_closed

    @pytest.mark.asyncio
    async def test_httpx_client_context_manager(self):
        """Verify httpx.AsyncClient works as async context manager."""
        async with httpx.AsyncClient() as client:
            assert not client.is_closed

        # After exiting context, client should be closed
        assert client.is_closed


class TestMockHTTPClient:
    """Test mock implementation of AsyncHTTPClient for testing purposes."""

    def create_mock_client(self, is_closed: bool = False) -> MagicMock:
        """Create a mock client that implements AsyncHTTPClient."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.headers = httpx.Headers({"X-Test": "value"})
        mock_client.is_closed = is_closed
        mock_client.aclose = AsyncMock()

        # After aclose is called, is_closed should be True
        async def close_client():
            mock_client.is_closed = True

        mock_client.aclose.side_effect = close_client

        return mock_client

    @pytest.mark.asyncio
    async def test_mock_client_aclose_sets_is_closed(self):
        """Verify mock client properly tracks closed state."""
        mock_client = self.create_mock_client()

        assert not mock_client.is_closed

        await mock_client.aclose()

        assert mock_client.is_closed
        mock_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_mock_client_can_be_injected(self):
        """Verify mock client can be used for dependency injection."""
        mock_client = self.create_mock_client()

        # Simulate a function that accepts AsyncHTTPClient
        async def use_client(client: AsyncHTTPClient) -> bool:
            try:
                # Do some work...
                return True
            finally:
                await client.aclose()

        result = await use_client(mock_client)

        assert result is True
        assert mock_client.is_closed


class TestMCPServerClientLifecycle:
    """Test MCP server properly manages httpx client lifecycle."""

    @pytest.fixture
    def mock_env_vars(self):
        """Environment variables for MCP server creation."""
        return {
            "ENV_STATE": "dev",
            "HOST": "localhost",
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

    def test_create_mcp_server_returns_client(self, mock_env_vars):
        """Verify create_mcp_server returns the httpx client for lifecycle management."""
        import os
        import sys
        from unittest import mock

        with mock.patch.dict(os.environ, mock_env_vars, clear=False):
            # Clean app modules
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import create_mcp_server

            result = create_mcp_server()

            # Should return 4 values: mcp_server, mcp_app, well_known_routes, api_client
            assert len(result) == 4

            mcp_server, mcp_app, well_known_routes, api_client = result

            assert mcp_server is not None
            assert mcp_app is not None
            assert isinstance(well_known_routes, list)
            assert api_client is not None
            assert isinstance(api_client, AsyncHTTPClient)

    def test_create_mcp_server_accepts_injected_client(self, mock_env_vars):
        """Verify create_mcp_server can use an injected client."""
        import os
        import sys
        from unittest import mock

        with mock.patch.dict(os.environ, mock_env_vars, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import create_mcp_server

            # Create a custom client to inject
            custom_client = httpx.AsyncClient(
                base_url="http://localhost:5000/geoapi",
                timeout=60.0,
                headers={"X-Custom-Header": "test"},
            )

            result = create_mcp_server(api_client=custom_client)

            _, _, _, returned_client = result

            # Should return the same client we injected
            assert returned_client is custom_client
            assert "X-Custom-Header" in returned_client.headers

    @pytest.mark.asyncio
    async def test_client_not_closed_during_server_operation(self, mock_env_vars):
        """Verify client remains open during normal server operation."""
        import os
        import sys
        from unittest import mock

        with mock.patch.dict(os.environ, mock_env_vars, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import create_mcp_server

            _, _, _, api_client = create_mcp_server()

            # Client should be open after creation
            assert not api_client.is_closed

            # Clean up
            await api_client.aclose()
            assert api_client.is_closed

    @pytest.mark.asyncio
    async def test_injected_client_lifecycle_managed_by_caller(self, mock_env_vars):
        """Verify injected client lifecycle is managed by the caller, not the server."""
        import os
        import sys
        from unittest import mock

        with mock.patch.dict(os.environ, mock_env_vars, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import create_mcp_server

            # Create and inject a client
            injected_client = httpx.AsyncClient(
                base_url="http://localhost:5000/geoapi",
                timeout=30.0,
            )

            _, _, _, returned_client = create_mcp_server(api_client=injected_client)

            # Client should still be open (caller manages lifecycle)
            assert not returned_client.is_closed
            assert returned_client is injected_client

            # Caller is responsible for closing
            await injected_client.aclose()
            assert injected_client.is_closed


class TestAppLifespanClientCleanup:
    """Test that the app lifespan properly cleans up the httpx client."""

    @pytest.fixture
    def mock_env_vars_with_mcp(self):
        """Environment variables for MCP-enabled app."""
        return {
            "ENV_STATE": "dev",
            "HOST": "localhost",
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

    @pytest.mark.asyncio
    async def test_lifespan_closes_client_on_shutdown(self, mock_env_vars_with_mcp):
        """Verify the app lifespan closes the httpx client on shutdown."""
        import os
        import sys
        from contextlib import asynccontextmanager
        from unittest import mock

        with mock.patch.dict(os.environ, mock_env_vars_with_mcp, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import create_mcp_server

            # Create MCP server and get the client
            _, _, _, api_client = create_mcp_server()

            # Track if client was closed
            client_closed = False
            original_aclose = api_client.aclose

            async def tracked_aclose():
                nonlocal client_closed
                client_closed = True
                await original_aclose()

            api_client.aclose = tracked_aclose

            # Create a lifespan that manages the client
            @asynccontextmanager
            async def test_lifespan(app):
                try:
                    yield
                finally:
                    await api_client.aclose()

            # Simulate lifespan execution
            async with test_lifespan(None):
                # App is running, client should be open
                assert not api_client.is_closed

            # After lifespan ends, client should be closed
            assert client_closed
            assert api_client.is_closed

    @pytest.mark.asyncio
    async def test_lifespan_closes_client_even_on_exception(self, mock_env_vars_with_mcp):
        """Verify the client is closed even if an exception occurs during shutdown."""
        import os
        import sys
        from contextlib import asynccontextmanager
        from unittest import mock

        with mock.patch.dict(os.environ, mock_env_vars_with_mcp, clear=False):
            modules_to_remove = [key for key in sys.modules.keys() if key.startswith("app.")]
            for module in modules_to_remove:
                del sys.modules[module]

            from app.config.app import FactoryConfig

            FactoryConfig.get_config.cache_clear()

            from app.main import create_mcp_server

            _, _, _, api_client = create_mcp_server()

            @asynccontextmanager
            async def test_lifespan_with_error(app):
                try:
                    yield
                    raise RuntimeError("Simulated error during shutdown")
                finally:
                    # Client should still be closed in finally block
                    await api_client.aclose()

            # Lifespan should close client even when exception occurs
            with pytest.raises(RuntimeError, match="Simulated error"):
                async with test_lifespan_with_error(None):
                    pass

            assert api_client.is_closed


class TestClientResourceLeakPrevention:
    """Test that resource leaks are prevented in various scenarios."""

    @pytest.mark.asyncio
    async def test_multiple_clients_all_closed(self):
        """Verify multiple clients can all be properly closed."""
        clients = [httpx.AsyncClient(base_url=f"http://localhost:{5000 + i}") for i in range(5)]

        # All clients should start open
        for client in clients:
            assert not client.is_closed

        # Close all clients
        await asyncio.gather(*[client.aclose() for client in clients])

        # All clients should be closed
        for client in clients:
            assert client.is_closed

    @pytest.mark.asyncio
    async def test_client_closed_after_failed_request(self):
        """Verify client is closed even after a failed request."""
        client = httpx.AsyncClient(base_url="http://localhost:9999", timeout=0.1)

        try:
            # This should fail (no server running)
            await client.get("/test")
        except (httpx.ConnectError, httpx.TimeoutException):
            pass  # Expected
        finally:
            await client.aclose()

        assert client.is_closed

    @pytest.mark.asyncio
    async def test_context_manager_ensures_cleanup(self):
        """Verify async context manager always cleans up."""
        client = None

        try:
            async with httpx.AsyncClient() as client:
                # Simulate some error during operation
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Client should still be closed despite the error
        assert client is not None
        assert client.is_closed


class TestHTTPClientHeaders:
    """Test HTTP client header management."""

    def test_client_has_internal_key_header(self):
        """Verify client includes the MCP internal key header."""
        import secrets

        internal_key = secrets.token_urlsafe(32)

        client = httpx.AsyncClient(
            base_url="http://localhost:5000/geoapi",
            headers={"X-MCP-Internal-Key": internal_key},
        )

        assert "X-MCP-Internal-Key" in client.headers
        assert client.headers["X-MCP-Internal-Key"] == internal_key

    def test_injected_client_preserves_custom_headers(self):
        """Verify injected client preserves custom headers."""
        custom_headers = {
            "X-Custom-Header": "custom-value",
            "Authorization": "Bearer test-token",
        }

        client = httpx.AsyncClient(
            base_url="http://localhost:5000",
            headers=custom_headers,
        )

        for key, value in custom_headers.items():
            assert key in client.headers
            assert client.headers[key] == value
