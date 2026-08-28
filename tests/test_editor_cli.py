"""`fastgeoapi config edit` — the entry point that separates the roles.

ADR-0008 ties the two roles to the command rather than to a setting: a
variable can be set by mistake in production — it happened here, with
`PROD_` where `DEV_` was read, and cost a deployment — while a
container's `CMD` does not reach a different CLI command unless someone
rewrites it.

So what this asserts is not that the command runs, but **what it hands
to the server**: the authoring application, on loopback, with its
per-run secret.
"""

import pytest
from typer.testing import CliRunner

from app.cli import app as cli


@pytest.fixture
def served(monkeypatch):
    """Capture what would have been served, without serving it."""
    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured["kwargs"] = kwargs

    monkeypatch.setattr("uvicorn.run", fake_run)
    return captured


def test_the_command_serves_the_authoring_application(served, tmp_path):
    source = tmp_path / "pygeoapi-config.yml"
    source.write_text("server: {}\n")

    result = CliRunner().invoke(cli, ["config", "edit", "--source", str(source)])

    assert result.exit_code == 0, result.output
    assert hasattr(served["app"].state, "editor_token"), "not the authoring application"


def test_it_stays_on_loopback(served, tmp_path):
    """Not a default that can be overridden into exposure."""
    source = tmp_path / "pygeoapi-config.yml"
    source.write_text("server: {}\n")

    CliRunner().invoke(cli, ["config", "edit", "--source", str(source)])

    assert served["kwargs"]["host"] == "127.0.0.1", served["kwargs"]


def test_it_prints_the_token_but_never_a_url_containing_it(served, tmp_path):
    """A secret in a URL outlives the session.

    It would stay in browser history, ride along in `Referer` towards
    anything a page loads, and sit in the shell history that printed it.
    The API takes it in a header for exactly that reason, so the command
    must not undo the argument by putting it in an address.
    """
    source = tmp_path / "pygeoapi-config.yml"
    source.write_text("server: {}\n")

    result = CliRunner().invoke(cli, ["config", "edit", "--source", str(source)])

    token = served["app"].state.editor_token
    assert token in result.output, result.output
    assert f"?token={token}" not in result.output, result.output
    assert f"={token}" not in result.output, result.output


def test_it_never_serves_the_reload_webhook(served, tmp_path):
    """The whole reason the roles are separate, checked at the entry point."""
    source = tmp_path / "pygeoapi-config.yml"
    source.write_text("server: {}\n")

    CliRunner().invoke(cli, ["config", "edit", "--source", str(source)])

    paths = {getattr(route, "path", "") for route in served["app"].routes}
    assert not any("config/reload" in path for path in paths), paths
