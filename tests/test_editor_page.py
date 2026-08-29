"""Serving the page, and the asymmetry that makes it possible.

The page has to be reachable **without** a token: it is where the token
gets typed in, so guarding it would leave no way to ever supply one. The
API behind it stays guarded. That asymmetry is deliberate and easy to
lose in a refactor, so it is pinned here.

What protects the page is what protects the whole authoring role — it is
not reachable from anywhere but this machine (ADR-0008). What the page
can *do* still needs the secret.
"""

from pathlib import Path

import pytest
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient

from app.editor.app import EDITOR_TOKEN_HEADER, build_authoring_app

PAGE = "<!doctype html><title>fastgeoapi editor</title>"


@pytest.fixture
def built(tmp_path) -> Path:
    """A compiled page, without needing a compiler.

    The tests must not depend on `npm run build` having been run: the
    Python suite has to pass on a checkout with no node in sight.
    """
    (tmp_path / "index.html").write_text(PAGE)
    return tmp_path


def test_the_page_is_served_without_a_token(built):
    """Because it is where the token is typed in."""
    app = build_authoring_app(host="127.0.0.1", page=built)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200, response.text
    assert "fastgeoapi editor" in response.text


def test_the_api_stays_guarded_even_though_the_page_is_not(built):
    """The asymmetry, stated as a test rather than left to be inferred."""
    app = build_authoring_app(host="127.0.0.1", page=built)

    with TestClient(app) as client:
        assert client.get("/editor/config").status_code == 401
        assert (
            client.get(
                "/editor/health", headers={EDITOR_TOKEN_HEADER: app.state.editor_token}
            ).status_code
            == 200
        )


def test_a_page_that_was_never_built_says_so(tmp_path):
    """A 404 would read as a bug in the editor rather than a missing step.

    The API is useful with no page at all — that is the whole reason it
    came first — so a missing build is not a startup failure. It is
    something to explain at the moment someone looks for the page.
    """
    app = build_authoring_app(host="127.0.0.1", page=tmp_path / "never-built")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 503, response.text
    assert "npm" in response.text, response.text


def test_the_serving_role_does_not_carry_the_page(create_app):
    """The deployment serves data, never an editor — assets included."""
    mounted = [
        route.app.directory
        for route in create_app().routes
        if isinstance(getattr(route, "app", None), StaticFiles)
    ]

    assert not any("editor" in str(directory) for directory in mounted), mounted


def test_every_route_under_editor_is_guarded(built):
    """Enumerated from the application, not listed by hand.

    The guard changed from covering everything to covering a prefix when
    the page arrived, and a prefix check is exactly the kind that grows a
    hole. Reading the route table means a route added later is covered by
    this test the day it is added, instead of the day someone remembers.

    `/editor/session` is the deliberate exception: it is how a browser
    gets in, and it checks the token in its own body.
    """
    from starlette.routing import Route

    app = build_authoring_app(host="127.0.0.1", page=built)
    guarded = [
        route
        for route in app.routes
        if isinstance(route, Route)
        and route.path.startswith("/editor")
        and route.path != "/editor/session"
    ]
    assert guarded, "no routes found to check — the enumeration is broken"

    with TestClient(app) as client:
        for route in guarded:
            for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
                response = client.request(method, route.path, json={"document": "a: 1"})
                assert response.status_code == 401, (
                    f"{method} {route.path} answered {response.status_code}"
                )
