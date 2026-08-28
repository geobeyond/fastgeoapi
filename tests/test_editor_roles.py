"""The two roles of one application, and why they never overlap.

ADR-0008 keeps the editor and the serving surface apart for two reasons,
and the second was measured only afterwards.

Powers: on one surface, whoever reaches it can both write the
configuration and activate it — together that is control of what the
server serves; apart, neither is enough on its own.

Caches: a dry run empties them. Measured — building a candidate takes
the plugin cache generation from 1 to 2 and leaves `l10n._cfg_cache`
empty. Beside a live server, every preview would degrade what it is
serving, taking HTTP latency from 24 back to 73 ms (ADR-0006), with
nobody able to connect cause to effect.
"""

import pytest
from starlette.testclient import TestClient

from app.editor.app import EDITOR_TOKEN_HEADER, build_authoring_app


def _paths(app) -> set[str]:
    found = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            found.add(path)
    return found


def test_the_authoring_role_does_not_carry_the_reload_webhook():
    """Writing a configuration must not come with activating it."""
    paths = _paths(build_authoring_app(host="127.0.0.1"))

    assert not any("config/reload" in path for path in paths), paths


def test_the_serving_role_does_not_carry_the_editor(create_app):
    """And the deployment must not carry the editor at all.

    Checked on the route table the application actually exposes, not on
    the intention — the same reasoning as the parity test of ADR-0003.
    """
    paths = _paths(create_app())

    assert not any(path.startswith("/editor") for path in paths), paths


def test_binding_beyond_loopback_is_refused():
    """A structural defence, not a warning.

    The authoring role has no OIDC chain in front of it: demanding an
    OAuth flow to edit a file on one's own machine would be ceremony
    without security. What replaces it is that the surface is not
    reachable from anywhere else — so a host that would expose it has to
    fail loudly, at startup, rather than serve.
    """
    with pytest.raises(ValueError, match="loopback"):
        build_authoring_app(host="0.0.0.0")


def test_requests_without_the_token_are_refused():
    """Loopback alone does not protect: other pages share the browser."""
    app = build_authoring_app(host="127.0.0.1")

    with TestClient(app) as client:
        assert client.get("/editor/config").status_code == 401


def test_the_token_works_for_more_than_one_request():
    """Per-run secret, not single use.

    An editor makes many calls; a token consumed on first use would let
    the page load and then break everything after it.
    """
    app = build_authoring_app(host="127.0.0.1")
    headers = {EDITOR_TOKEN_HEADER: app.state.editor_token}

    with TestClient(app) as client:
        assert client.get("/editor/health", headers=headers).status_code == 200
        assert client.get("/editor/health", headers=headers).status_code == 200


def test_a_wrong_token_is_refused():
    app = build_authoring_app(host="127.0.0.1")

    with TestClient(app) as client:
        response = client.get("/editor/health", headers={EDITOR_TOKEN_HEADER: "not-it"})

    assert response.status_code == 401
