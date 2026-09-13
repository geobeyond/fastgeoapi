"""A 401 has to say how to authenticate (RFC 6750 §3, RFC 7235 §4.1).

A protected resource that refuses a request without telling the client
which scheme to use, and against which resource, is a dead end: the
client has nothing to act on. The MCP surface has answered with a
challenge since it was written (`test_mcp_oauth_e2e.py`); these pin the
same promise for the OGC API surface, which is served by our own
middleware.

Imports stay at module level and the middleware is driven directly:
building the whole application would test the wiring, not the answer.
"""

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.auth.auth_interface import AuthInterface
from app.auth.exceptions import Oauth2Error
from app.auth.oauth2 import Oauth2Provider
from app.middleware.oauth2 import Oauth2Middleware

AUDIENCE = "https://example.org/geoapi/"


class Refusing(AuthInterface):
    """An authentication that never accepts anything."""

    async def authenticate(self, request: Request) -> dict:
        raise Oauth2Error("nope")


@pytest.fixture
def client() -> TestClient:
    """The middleware in front of something that would answer 200."""
    served = Starlette(routes=[Route("/geoapi/", lambda request: JSONResponse({"ok": True}))])
    return TestClient(
        Oauth2Middleware(served, config=Oauth2Provider(authentication=[Refusing()])),
        raise_server_exceptions=False,
    )


def test_a_request_without_credentials_is_told_which_scheme_to_use(client):
    response = client.get("/geoapi/")

    assert response.status_code == 401
    challenge = response.headers.get("www-authenticate", "")
    assert challenge.startswith("Bearer "), challenge
    assert 'realm="' in challenge, challenge


def test_no_credentials_means_no_error_attribute(client):
    """RFC 6750 §3.1: `error` is for a request that carried credentials.

    A client discovering the API sends nothing the first time, and an
    `error="invalid_token"` there would say its token was rejected when
    it never had one.
    """
    challenge = client.get("/geoapi/").headers.get("www-authenticate", "")

    assert challenge.startswith("Bearer "), challenge  # there is a challenge at all
    assert "error=" not in challenge, challenge


def test_a_rejected_token_is_told_it_was_the_token(client):
    challenge = client.get(
        "/geoapi/", headers={"Authorization": "Bearer not-a-real-token"}
    ).headers.get("www-authenticate", "")

    assert 'error="invalid_token"' in challenge, challenge


def test_the_challenge_names_the_audience_a_token_needs(client, monkeypatch):
    """The realm is the resource identifier tokens must be audienced for.

    Without it a client that reaches several deployments cannot tell which
    `resource` to ask its authorization server for — the parameter whose
    absence is the single most common reason a perfectly valid token is
    refused.
    """
    import app.middleware.oauth2 as middleware

    monkeypatch.setattr(middleware.cfg, "OAUTH2_EXPECTED_AUDIENCE", AUDIENCE, raising=False)

    challenge = client.get("/geoapi/").headers.get("www-authenticate", "")

    assert f'realm="{AUDIENCE}"' in challenge, challenge
