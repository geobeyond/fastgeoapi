"""Test middlewares."""

import os

import pytest
from httpx import ASGITransport
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_pygeoapi_links_behind_proxy(reverse_proxy_enabled) -> None:
    """Test presence of reverse proxy base urls in links."""
    transport = ASGITransport(app=reverse_proxy_enabled)
    async with AsyncClient(
        transport=transport, base_url="http://testserver", timeout=30
    ) as client:
        _proto = "https"
        _host = "proxy.example.com"
        # Get FASTGEOAPI_CONTEXT from environment (set by create_app)
        context = os.environ.get("FASTGEOAPI_CONTEXT", "/geoapi")
        response = await client.get(
            f"{context}/collections",
            headers={
                "X-Forwarded-Proto": _proto,
                "X-Forwarded-Host": _host,
            },
        )
        assert response.status_code == 200
        links = response.json()["links"]
        for link in links:
            href = link["href"]
            assert _proto in href
            assert _host in href
