"""The swap is atomic and both faces (mount, MCP transport) see the same app."""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from app.pygeoapi.holder import PygeoapiHolder


def _app(tag: str) -> Starlette:
    async def whoami(request):
        return JSONResponse({"app": tag})

    return Starlette(routes=[Route("/whoami", whoami)])


@pytest.mark.asyncio
async def test_empty_holder_answers_503():
    transport = httpx.ASGITransport(app=PygeoapiHolder())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/whoami")).status_code == 503


@pytest.mark.asyncio
async def test_swap_changes_served_app_between_requests():
    holder = PygeoapiHolder()
    holder.swap(_app("v1"), etag="e1")
    transport = httpx.ASGITransport(app=holder)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/whoami")).json() == {"app": "v1"}
        holder.swap(_app("v2"), etag="e2")
        assert (await client.get("/whoami")).json() == {"app": "v2"}
    assert holder.etag == "e2"
