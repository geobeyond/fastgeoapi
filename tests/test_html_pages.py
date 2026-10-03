"""Pages rendered from a route's JSON: negotiation, errors, headers, languages.

``app.*`` is imported at the top of this module.
"""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from app.html.pages import NativePages, Page, format_instant, format_number, with_query
from app.pygeoapi.factory import build_api, build_openapi, build_routes
from tests.html_fixtures import SERVER_URL, config, fake_build

CQL2 = "http://www.opengis.net/spec/cql2/1.0/conf/basic-cql2"

TEMPLATES = {
    "_base.html": (
        '<html lang="{{ lang }}"><head><title>{{ title }}</title>'
        '<link rel="canonical" href="{{ canonical }}">'
        '{% for href in styles %}<link rel="stylesheet" href="{{ href }}">{% endfor %}'
        '{% for src in scripts %}<script type="module" src="{{ src }}"></script>{% endfor %}'
        "</head><body>{% block content %}{% endblock %}</body></html>\n"
    ),
    "conformance.html": (
        '{% extends "_base.html" %}{% block content %}<h1>{{ _("Collections") }}</h1>'
        "{% for uri in classes %}<p>{{ uri }}</p>{% endfor %}{% endblock %}\n"
    ),
    "plain.html": (
        '{% extends "_base.html" %}{% block content %}<p>{{ greeting }}</p>{% endblock %}\n'
    ),
}

CATALOG = (
    'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
    'msgid "Collections"\nmsgstr "Collezioni"\n'
)

SILENT_CALLS = []


def _conformance(context):
    return {"title": "Conformance", "classes": context.document["conformsTo"]}


def _plain(context):
    return {
        "title": "Plain",
        "greeting": f"{context.url}|{context.path_params.get('collection_id')}",
    }


async def _echo(request):
    return JSONResponse({"method": request.method, "links": []})


async def _silent(request):
    SILENT_CALLS.append(request.url.path)
    return JSONResponse({"links": []})


async def _image(request):
    return Response(b"\x89PNG", media_type="image/png")


PAGES = {
    "/conformance": Page("conformance.html", _conformance, islands=("pages/api-docs.ts",)),
    "/collections/{collection_id:path}/queryables": Page("plain.html", _plain),
    "/echo": Page("plain.html", _plain),
    "/silent": Page("plain.html", _plain, needs_document=False),
    "/image": Page("plain.html", _plain),
}


def _directories(root):
    templates = root / "templates"
    templates.mkdir()
    for name, text in TEMPLATES.items():
        (templates / name).write_text(text)
    catalog = root / "locale" / "it" / "LC_MESSAGES"
    catalog.mkdir(parents=True)
    (catalog / "messages.po").write_text(CATALOG)
    return templates, root / "locale", fake_build(root / "static")


def _client(templates, locale, static):
    api_config = config()
    api = build_api(api_config, build_openapi(api_config))
    routes = [
        *build_routes(api, specs=frozenset({"core"})),
        Route("/echo", _echo, methods=["GET", "POST"]),
        Route("/silent", _silent),
        Route("/image", _image),
    ]
    pages = NativePages(PAGES, templates, locale, static)
    app = Starlette(routes=[Mount("/geoapi", routes=pages.wrap(api, routes))])
    return TestClient(app, base_url="http://internal:8000", raise_server_exceptions=False)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    templates, locale, static = _directories(tmp_path_factory.mktemp("pages"))
    return _client([templates], locale, static)


def test_an_html_request_renders_the_page_from_the_routes_json(client):
    r = client.get("/geoapi/conformance", params={"f": "html"})

    assert (r.status_code, r.headers["content-type"]) == (200, "text/html; charset=utf-8")
    assert f"<p>{CQL2}</p>" in r.text


def test_a_browser_asking_for_html_gets_the_page(client):
    r = client.get("/geoapi/conformance", headers={"Accept": "text/html,application/xhtml+xml"})

    assert r.headers["content-type"] == "text/html; charset=utf-8"


def test_a_json_request_never_reaches_the_page(client):
    r = client.get("/geoapi/conformance", params={"f": "json"})

    assert r.headers["content-type"] == "application/json"
    assert CQL2 in r.json()["conformsTo"]


def test_an_error_keeps_its_json_and_its_status(client):
    r = client.get("/geoapi/collections/nope/queryables", params={"f": "html"})

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")
    assert r.json()["code"] == "NotFound"


def test_a_route_without_a_page_keeps_pygeoapis_html(client):
    r = client.get("/geoapi/collections", params={"f": "html"})

    assert r.status_code == 200
    assert "bootstrap" in r.text  # pygeoapi's own template loads Bootstrap


def test_the_page_url_is_built_on_the_configured_server_url(client):
    r = client.get("/geoapi/conformance", params={"lang": "it"}, headers={"Accept": "text/html"})

    assert f'<link rel="canonical" href="{SERVER_URL}/conformance?lang=it&amp;f=html">' in r.text


def test_the_view_gets_the_page_url_and_the_path_parameters(client):
    r = client.get("/geoapi/collections/lakes/queryables", params={"f": "html"})

    assert f"<p>{SERVER_URL}/collections/lakes/queryables?f=html|lakes</p>" in r.text


def test_the_headers_name_the_language_the_variants_and_what_varies(client):
    r = client.get("/geoapi/conformance", params={"f": "html", "lang": "it"})
    url = f"{SERVER_URL}/conformance?lang=it"

    assert r.headers["content-language"] == "it-IT"
    assert r.headers["vary"] == "Accept, Accept-Language"
    assert r.headers["link"] == (
        f'<{url}&f=html>; rel="self"; type="text/html", '
        f'<{url}&f=json>; rel="alternate"; type="application/json"'
    )


@pytest.mark.parametrize(
    ("params", "headers", "lang", "heading"),
    [
        ({"lang": "it"}, {}, "it-IT", "Collezioni"),
        ({}, {"Accept-Language": "it"}, "it-IT", "Collezioni"),
        ({"lang": "fr-CA"}, {}, "fr-CA", "Collections"),
        ({}, {}, "en-US", "Collections"),
    ],
)
def test_the_interface_speaks_the_negotiated_language(client, params, headers, lang, heading):
    r = client.get("/geoapi/conformance", params={"f": "html", **params}, headers=headers)

    assert f'<html lang="{lang}">' in r.text
    assert f"<h1>{heading}</h1>" in r.text


def test_the_page_links_its_stylesheet_and_its_island_from_the_manifest(client):
    r = client.get("/geoapi/conformance", params={"f": "html"})
    files = f"{SERVER_URL}/_html/assets"

    assert f'<link rel="stylesheet" href="{files}/style-4f2a.css">' in r.text
    assert f'<link rel="stylesheet" href="{files}/api-docs-77aa.css">' in r.text
    assert f'<script type="module" src="{files}/api-docs-77aa.js"></script>' in r.text


def test_a_page_that_needs_no_document_does_not_ask_its_route(client):
    page = client.get("/geoapi/silent", params={"f": "html"})
    data = client.get("/geoapi/silent", params={"f": "json"})

    assert (page.status_code, data.status_code) == (200, 200)
    assert SILENT_CALLS == ["/geoapi/silent"]  # the JSON request, and only that


def test_other_methods_go_straight_to_the_route(client):
    r = client.post("/geoapi/echo", params={"f": "html"})

    assert r.json() == {"method": "POST", "links": []}


def test_a_head_request_gets_the_page_headers(client):
    r = client.head("/geoapi/conformance", params={"f": "html"})

    assert (r.status_code, r.headers["content-type"]) == (200, "text/html; charset=utf-8")


def test_an_answer_that_is_not_json_goes_out_as_it_is(client):
    r = client.get("/geoapi/image", params={"f": "html"})

    assert (r.headers["content-type"], r.content) == ("image/png", b"\x89PNG")


def test_a_template_of_the_first_directory_overrides_the_next(tmp_path):
    templates, locale, static = _directories(tmp_path)
    override = tmp_path / "override"
    override.mkdir()
    (override / "plain.html").write_text(
        '{% extends "_base.html" %}{% block content %}<p>override</p>{% endblock %}\n'
    )
    client = _client([override, templates], locale, static)

    assert "<p>override</p>" in client.get("/geoapi/echo", params={"f": "html"}).text
    assert f"<p>{CQL2}</p>" in client.get("/geoapi/conformance", params={"f": "html"}).text


def test_with_query_sets_one_parameter_and_keeps_the_others():
    url = with_query("https://example.org/a?f=json&lang=it&x=1", f="html")

    assert url == "https://example.org/a?lang=it&x=1&f=html"


def test_dates_and_numbers_are_written_as_the_page_language_writes_them():
    assert format_instant("2026-10-03T10:00:00Z", "it").startswith("3 ott 2026")
    assert (format_instant(None, "it"), format_instant("soon", "it")) == ("", "soon")
    assert format_number(559082264.028717, "it") == "559.082.264,029"
    assert (format_number(559082264.028717, "en"), format_number(None, "en")) == (
        "559,082,264.029",
        "",
    )
