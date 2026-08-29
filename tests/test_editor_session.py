"""Handing the token to a browser without putting it in a URL.

The API takes the token in a header, which is right for `curl` and wrong
for a page: to send a header the page needs the token already, and the
only way to give it one through an address is to put the secret in the
address. A secret there outlives the session — browser history, the
`Referer` sent to anything the page loads, the shell history of whoever
printed it.

So the page asks for it, posts it in a body, and gets back a cookie.
Francesco's reason for preferring this is the one that matters most: the
browser binds a cookie to the origin that set it, so it can never leave
for the deployment — a confinement the header does not have.
"""

import pytest
from starlette.testclient import TestClient

from app.editor.app import EDITOR_TOKEN_COOKIE, EDITOR_TOKEN_HEADER, build_authoring_app


@pytest.fixture
def app():
    return build_authoring_app(host="127.0.0.1")


def test_the_schema_is_served_for_the_form(app):
    """The form is generated from it, so the browser has to have it."""
    with TestClient(app) as client:
        response = client.get(
            "/editor/schema", headers={EDITOR_TOKEN_HEADER: app.state.editor_token}
        )

    assert response.status_code == 200, response.text
    assert "server" in response.json()["properties"], response.json()["properties"].keys()
    assert "resources" in response.json()["properties"]


def test_the_schema_is_not_public(app):
    with TestClient(app) as client:
        assert client.get("/editor/schema").status_code == 401


def test_the_session_takes_the_token_in_a_body_and_answers_with_a_cookie(app):
    """The one endpoint reachable without the token, because it is how one gets in."""
    with TestClient(app) as client:
        response = client.post("/editor/session", json={"token": app.state.editor_token})

    assert response.status_code == 200, response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie, cookie
    assert "SameSite=strict" in cookie.replace("Strict", "strict"), cookie


def test_the_session_never_says_the_token_back(app):
    """An answer carrying it would put it back where it must not be.

    The page has it already; repeating it only creates another copy to
    leak — in a response body that a proxy, a log or a devtools session
    would happily keep.
    """
    with TestClient(app) as client:
        response = client.post("/editor/session", json={"token": app.state.editor_token})

    assert app.state.editor_token not in response.text, response.text


def test_a_wrong_token_gets_no_cookie(app):
    with TestClient(app) as client:
        response = client.post("/editor/session", json={"token": "not-it"})

    assert response.status_code == 401, response.text
    assert "set-cookie" not in response.headers, response.headers


def test_the_cookie_is_accepted_in_place_of_the_header(app):
    """What the page relies on: one exchange, then ordinary requests."""
    with TestClient(app) as client:
        client.post("/editor/session", json={"token": app.state.editor_token})

        assert client.get("/editor/health").status_code == 200


def test_a_wrong_cookie_is_refused(app):
    with TestClient(app) as client:
        client.cookies.set(EDITOR_TOKEN_COOKIE, "not-it")

        assert client.get("/editor/health").status_code == 401
