"""What only fastgeoapi can tell you about a configuration.

The editor works for someone who has nothing but pygeoapi — that is
deliberate, and tested next door. This is the other half: when
fastgeoapi *is* what you are running, the same document decides two more
things that no pygeoapi tool can report.

Which OGC API specifications get mounted, because fastgeoapi builds the
route table from the resources rather than serving everything (ADR-0005).
And which MCP tools an agent would see, because those are generated from
the OpenAPI this very dry run has already built.

The flag is opt-in. Turned on where it cannot be answered — no fastmcp
installed, say — the answer is a line saying why, never a failure: that
would put back, behind a flag, the barrier the editor just removed.
"""

from pathlib import Path

import pytest

from app.editor.inspect import dry_run

SOURCE = Path("tests/data/pygeoapi-config.yml").read_text()


@pytest.fixture(autouse=True)
def interpolation(monkeypatch):
    for name, value in (
        ("HOST", "0.0.0.0"),
        ("PORT", "5000"),
        ("PYGEOAPI_BASEURL", "http://localhost:5000"),
        ("FASTGEOAPI_CONTEXT", "/geoapi"),
    ):
        monkeypatch.setenv(name, value)


def test_a_plain_dry_run_says_nothing_about_either(interpolation):
    """The default stays what a pygeoapi user would recognise."""
    outcome = dry_run(SOURCE)

    assert outcome.specs == []
    assert outcome.tools == []


def test_it_reports_the_specifications_the_configuration_would_mount():
    outcome = dry_run(SOURCE, augmented=True)

    assert outcome.ok, outcome.problems
    # `core` is always there; `features` because the fixture serves them.
    assert "core" in outcome.specs, outcome.specs
    assert "features" in outcome.specs, outcome.specs


def test_it_reports_the_tools_an_agent_would_see():
    """Derived from the document this run already built, not guessed.

    Naming is FastMCP's, and re-deriving the rules here would drift from
    it the first time upstream changed them.
    """
    outcome = dry_run(SOURCE, augmented=True)

    assert outcome.tools, outcome.not_reported
    assert any("Collections" in tool for tool in outcome.tools), outcome.tools


def test_what_cannot_be_answered_is_said_rather_than_raised(monkeypatch):
    """Asking for more than is installed is not an error.

    Someone running this against a pygeoapi they do not serve with
    fastgeoapi may still pass the flag. Failing would hand them back the
    barrier that was just taken away.
    """
    # The module and the function are taken together, here, rather than
    # patching this module while calling the one imported at the top.
    # Another test purges `sys.modules`, so those are two different
    # module objects by the time this runs and the patch lands on the
    # one nobody calls. Fifth time this trap has been sprung.
    import app.editor.inspect as inspect

    def unavailable(*args, **kwargs):
        raise ImportError("no fastmcp here")

    monkeypatch.setattr(inspect, "_mcp_tools", unavailable)

    outcome = inspect.dry_run(SOURCE, augmented=True)

    assert outcome.ok, outcome.problems
    assert outcome.tools == []
    assert any("tools" in line for line in outcome.not_reported), outcome.not_reported
    # The half that does not need fastmcp still answers.
    assert "core" in outcome.specs


def test_the_flag_reaches_the_endpoint(tmp_path):
    """Wired end to end, since a flag that stops at the CLI is no flag."""
    from starlette.testclient import TestClient

    from app.editor.app import EDITOR_TOKEN_HEADER, build_authoring_app

    target = tmp_path / "pygeoapi-config.yml"
    target.write_text(SOURCE)

    for augmented, expected in ((False, False), (True, True)):
        app = build_authoring_app(host="127.0.0.1", source=str(target), augmented=augmented)
        with TestClient(app) as client:
            client.headers[EDITOR_TOKEN_HEADER] = app.state.editor_token
            body = client.post("/editor/dry-run", json={"document": SOURCE}).json()

        assert bool(body["specs"]) is expected, body
        assert bool(body["tools"]) is expected, body
