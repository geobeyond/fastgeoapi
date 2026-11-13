"""Links behind a proxy that forwards another host name.

``app.*`` is imported at the top of this module.
"""

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.middleware import proxy

INTERNAL = "http://internal.example:5000"
FORWARDED = {"x-forwarded-proto": "https", "x-forwarded-host": "public.example"}


async def _page(request):
    return HTMLResponse(
        f'<a href="{INTERNAL}/geoapi/collections?f=html">collections</a>',
        headers={"Link": f'<{INTERNAL}/geoapi/?f=html>; rel="self"'},
    )


async def _json(request):
    return JSONResponse({"links": [{"href": f"{INTERNAL}/geoapi/?f=json"}]})


def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr(proxy.cfg, "PYGEOAPI_BASEURL", INTERNAL)
    app = Starlette(routes=[Route("/page", _page), Route("/json", _json)])
    app.add_middleware(proxy.ForwardedLinksMiddleware)
    return TestClient(app)


def test_a_page_with_a_charset_is_rewritten_to_the_forwarded_host(monkeypatch):
    r = _client(monkeypatch).get("/page", headers=FORWARDED)

    assert 'href="https://public.example/geoapi/collections?f=html"' in r.text
    assert INTERNAL not in r.text


def test_the_link_header_follows_the_forwarded_host(monkeypatch):
    r = _client(monkeypatch).get("/page", headers=FORWARDED)

    assert r.headers["link"] == '<https://public.example/geoapi/?f=html>; rel="self"'


def test_json_is_still_rewritten(monkeypatch):
    r = _client(monkeypatch).get("/json", headers=FORWARDED)

    assert r.json()["links"][0]["href"] == "https://public.example/geoapi/?f=json"


def test_without_forwarded_headers_nothing_changes(monkeypatch):
    r = _client(monkeypatch).get("/page")

    assert f"{INTERNAL}/geoapi/collections" in r.text
    assert r.headers["link"] == f'<{INTERNAL}/geoapi/?f=html>; rel="self"'
