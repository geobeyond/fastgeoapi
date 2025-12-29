"""HTTP Client interface for async HTTP operations.

This module defines the Protocol for async HTTP clients used by the MCP server.
The Protocol allows for dependency injection and proper lifecycle management,
enabling clean resource cleanup and easier testing with mock implementations.
"""

from typing import Any, Protocol, runtime_checkable

import httpx


@runtime_checkable
class AsyncHTTPClient(Protocol):
    """Protocol defining the interface for async HTTP clients.

    This protocol is designed to be compatible with httpx.AsyncClient
    while allowing for alternative implementations (e.g., for testing).

    The key requirement is proper lifecycle management through the
    `aclose()` method, which must be called when the client is no longer needed
    to prevent resource leaks.

    Example usage with httpx.AsyncClient:
        ```python
        async with httpx.AsyncClient() as client:
            response = await client.get("https://api.example.com")
        ```

    Example usage with dependency injection:
        ```python
        def create_mcp_server(client: AsyncHTTPClient | None = None):
            if client is None:
                client = httpx.AsyncClient(base_url="...", timeout=30.0)
            # ... use client
            return mcp_server, mcp_app, well_known_routes, client
        ```
    """

    @property
    def headers(self) -> httpx.Headers:
        """Return the default headers for requests."""
        ...

    async def get(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a GET request.

        Parameters
        ----------
        url : str
            The URL to request.
        params : dict[str, Any] | None
            Query parameters to include in the request.
        headers : dict[str, str] | None
            Additional headers to include in the request.
        **kwargs : Any
            Additional arguments passed to the underlying client.

        Returns
        -------
        httpx.Response
            The HTTP response.
        """
        ...

    async def post(
        self,
        url: str,
        *,
        content: bytes | None = None,
        data: dict[str, Any] | None = None,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a POST request.

        Parameters
        ----------
        url : str
            The URL to request.
        content : bytes | None
            Raw content to send in the request body.
        data : dict[str, Any] | None
            Form data to send in the request body.
        json : Any | None
            JSON data to send in the request body.
        params : dict[str, Any] | None
            Query parameters to include in the request.
        headers : dict[str, str] | None
            Additional headers to include in the request.
        **kwargs : Any
            Additional arguments passed to the underlying client.

        Returns
        -------
        httpx.Response
            The HTTP response.
        """
        ...

    async def put(
        self,
        url: str,
        *,
        content: bytes | None = None,
        data: dict[str, Any] | None = None,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a PUT request.

        Parameters
        ----------
        url : str
            The URL to request.
        content : bytes | None
            Raw content to send in the request body.
        data : dict[str, Any] | None
            Form data to send in the request body.
        json : Any | None
            JSON data to send in the request body.
        params : dict[str, Any] | None
            Query parameters to include in the request.
        headers : dict[str, str] | None
            Additional headers to include in the request.
        **kwargs : Any
            Additional arguments passed to the underlying client.

        Returns
        -------
        httpx.Response
            The HTTP response.
        """
        ...

    async def delete(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send a DELETE request.

        Parameters
        ----------
        url : str
            The URL to request.
        params : dict[str, Any] | None
            Query parameters to include in the request.
        headers : dict[str, str] | None
            Additional headers to include in the request.
        **kwargs : Any
            Additional arguments passed to the underlying client.

        Returns
        -------
        httpx.Response
            The HTTP response.
        """
        ...

    async def request(
        self,
        method: str,
        url: str,
        *,
        content: bytes | None = None,
        data: dict[str, Any] | None = None,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request with the specified method.

        Parameters
        ----------
        method : str
            The HTTP method to use (GET, POST, PUT, DELETE, etc.).
        url : str
            The URL to request.
        content : bytes | None
            Raw content to send in the request body.
        data : dict[str, Any] | None
            Form data to send in the request body.
        json : Any | None
            JSON data to send in the request body.
        params : dict[str, Any] | None
            Query parameters to include in the request.
        headers : dict[str, str] | None
            Additional headers to include in the request.
        **kwargs : Any
            Additional arguments passed to the underlying client.

        Returns
        -------
        httpx.Response
            The HTTP response.
        """
        ...

    async def aclose(self) -> None:
        """Close the client and release all resources.

        This method MUST be called when the client is no longer needed
        to prevent resource leaks (open connections, file descriptors, etc.).

        For httpx.AsyncClient, this closes the underlying connection pool.

        Example:
            ```python
            client = httpx.AsyncClient()
            try:
                response = await client.get("https://api.example.com")
            finally:
                await client.aclose()
            ```

        Or using async context manager:
            ```python
            async with httpx.AsyncClient() as client:
                response = await client.get("https://api.example.com")
            # client.aclose() is called automatically
            ```
        """
        ...

    @property
    def is_closed(self) -> bool:
        """Return whether the client has been closed.

        Returns
        -------
        bool
            True if the client has been closed, False otherwise.
        """
        ...
