"""Test middlewares."""

import pytest
from httpx import AsyncClient

from app.config.app import configuration as cfg


@pytest.mark.asyncio
async def test_pygeoapi_links_behind_proxy(
    create_app_with_reverse_proxy_enabled
) -> None:
    app = create_app_with_reverse_proxy_enabled()
    async with AsyncClient(app=app) as client:
        PROTO = "https"
        HOST = "proxy.example.com"
        response = await client.get(
            f"{cfg.APP_URI}{cfg.FASTGEOAPI_CONTEXT}/collections",
            headers={
                "X-Forwarded-Proto": PROTO,
                "X-Forwarded-Host": HOST,
            },
        )
        assert response.status_code == 200
        links = response.json()["links"]
        for link in links:
            href = link["href"]
            assert PROTO in href
            assert HOST in href
