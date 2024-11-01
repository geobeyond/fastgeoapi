"""Test middlewares."""

import pytest
from httpx import ASGITransport
from httpx import AsyncClient

from app.config.app import configuration as cfg


@pytest.mark.asyncio
async def test_pygeoapi_links_behind_proxy(reverse_proxy_enabled) -> None:
    """Test presence of reverse proxy base urls in links."""
    transport = ASGITransport(app=reverse_proxy_enabled)
    async with AsyncClient(transport=transport, timeout=30) as client:
        _proto = "https"
        _host = "proxy.example.com"
        response = await client.get(
            f"{cfg.APP_URI}{cfg.FASTGEOAPI_CONTEXT}/collections",
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
