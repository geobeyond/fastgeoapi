"""Pages that ask more than their route: empty fields, related routes, a 400 shown again.

``app.*`` is imported at the top of this module.
"""

import asyncio
import contextlib

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.html.pages import NativePages, Page, Related, without_query
from app.pygeoapi.factory import build_api, build_openapi
from tests.html_fixtures import SERVER_URL, config

TEMPLATE = (
    '<title>{{ title }}</title><link rel="canonical" href="{{ canonical }}"><p>{{ shown }}</p>\n'
)


async def _thing(request):
    query = {key: value for key, value in request.query_params.items() if key != "f"}
    return JSONResponse({"name": request.path_params["name"], "query": query, "links": []})


async def _named(request):
    name = request.path_params["name"]
    return JSONResponse(
        {
            "name": name,
            "query": {},
            "links": [
                {
                    "href": f"{SERVER_URL}/named/{name}?f=json",
                    "rel": "self",
                    "type": "application/json",
                }
            ],
        }
    )


async def _details(request):
    name = request.path_params["name"]
    if name == "raising":
        raise RuntimeError("the data source failed")
    if name == "broken":
        return JSONResponse({"code": "NoApplicableCode", "description": "broken"}, status_code=500)
    if name == "missing":
        return JSONResponse({"code": "NotFound", "description": "no such thing"}, status_code=404)
    return JSONResponse({"detail": name, "lang": request.query_params.get("lang")})


async def _strict(request):
    if "bbox" in request.query_params:
        return JSONResponse(
            {"code": "InvalidParameterValue", "description": "bbox is wrong"}, status_code=400
        )
    return JSONResponse({"links": []})


async def _demanding(request):
    return JSONResponse(
        {"code": "MissingParameterValue", "description": "missing coords parameter"},
        status_code=400,
    )


def _shown(context):
    document = context.document or {}
    query = " ".join(f"{key}={value}" for key, value in sorted(document.get("query", {}).items()))
    details = context.related.get("details")
    detail = "none" if details is None else f"{details['detail']}/{details['lang']}"
    params = " ".join(f"{key}={value}" for key, value in sorted(context.params.items()))
    return {
        "title": "Shown",
        "shown": f"query[{query}] details[{detail}] error[{context.error}] params[{params}]",
    }


def _where(context):
    loops = []
    with contextlib.suppress(RuntimeError):
        loops.append(asyncio.get_running_loop())
    return {"title": "Thread", "shown": f"loops[{len(loops)}]"}


def _renamed(params):
    return {"name": params["name"].upper()}


PAGES = {
    "/things/{name}": Page(
        "plain.html", _shown, related=(Related("details", "/things/{name}/details"),)
    ),
    "/required/{name}": Page(
        "plain.html",
        _shown,
        related=(Related("details", "/things/{name}/details", required=True),),
    ),
    "/renamed/{name}": Page(
        "plain.html",
        _shown,
        related=(Related("details", "/things/{name}/details", adjust=_renamed),),
    ),
    "/strict": Page("plain.html", _shown, on_bad_request=True),
    "/demanding": Page("plain.html", _shown, on_bad_request=True),
    "/thread": Page("plain.html", _where, needs_document=False),
    "/named/{name}": Page("plain.html", _shown),
}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("requests")
    (root / "plain.html").write_text(TEMPLATE)
    api_config = config()
    api = build_api(api_config, build_openapi(api_config))
    routes = [
        Route("/things/{name}", _thing),
        Route("/things/{name}/details", _details),
        Route("/required/{name}", _thing),
        Route("/renamed/{name}", _thing),
        Route("/strict", _strict),
        Route("/demanding", _demanding),
        Route("/thread", _thing),
        Route("/named/{name}", _named),
    ]
    pages = NativePages(PAGES, [root], root / "locale", root / "static")
    return TestClient(Starlette(routes=pages.wrap(api, routes)), raise_server_exceptions=False)


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


def test_a_related_route_that_raises_is_none(client):
    r = _page(client, "/things/raising")

    assert r.status_code == 200
    assert "details[none]" in r.text


def test_a_path_beyond_latin_1_is_a_page_with_encoded_urls(client):
    r = _page(client, "/named/東京")
    encoded = "%E6%9D%B1%E4%BA%AC"

    assert r.status_code == 200
    assert f'<link rel="canonical" href="{SERVER_URL}/named/{encoded}?f=html">' in r.text
    assert f"<{SERVER_URL}/named/{encoded}?f=json>" in r.headers["link"]


def test_empty_fields_reach_neither_the_route_nor_the_page_url(client):
    html = _page(client, "/things/a", bbox="", limit="5").text

    assert "query[limit=5]" in html
    assert "params[limit=5]" in html
    assert f'<link rel="canonical" href="{SERVER_URL}/things/a?limit=5&amp;f=html">' in html


def test_a_related_route_answers_with_the_page_path_and_language(client):
    assert "details[a/it]" in _page(client, "/things/a", lang="it").text


def test_a_related_route_can_be_asked_with_other_path_parameters(client):
    assert "details[A/None]" in _page(client, "/renamed/a").text


def test_a_related_route_that_fails_is_none(client):
    r = _page(client, "/things/broken")

    assert r.status_code == 200
    assert "details[none]" in r.text


def test_a_required_route_that_fails_is_the_answer(client):
    r = _page(client, "/required/missing")

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")
    assert r.json()["description"] == "no such thing"


def test_a_page_that_takes_its_400_renders_it_again(client):
    r = _page(client, "/strict", bbox="x")

    assert (r.status_code, r.headers["content-type"]) == (400, "text/html; charset=utf-8")
    assert "error[bbox is wrong] params[bbox=x]" in r.text


def test_the_400_stays_json_for_a_json_request(client):
    r = client.get("/strict", params={"f": "json", "bbox": "x"})

    assert (r.status_code, r.headers["content-type"]) == (400, "application/json")


def test_a_refused_request_without_parameters_is_a_blank_form(client):
    r = _page(client, "/demanding", lang="it")

    assert r.status_code == 200
    assert "error[None] params[lang=it]" in r.text


def test_the_view_runs_off_the_event_loop(client):
    assert "loops[0]" in _page(client, "/thread").text


def test_without_query_drops_the_named_parameters():
    url = without_query("https://example.org/a?name=x&limit=2&f=html", "name")

    assert url == "https://example.org/a?limit=2&f=html"
