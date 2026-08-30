"""The editor has to work for someone who only has pygeoapi.

Installing fastgeoapi to edit a pygeoapi configuration is a reasonable
thing to want: the editor's dry run builds the whole API and reads its
data sources, which nothing upstream offers. That only holds if the
command runs **without fastgeoapi being configured at all** — no
`HOST`, no `PORT`, no authentication chain, no `.env`.

It did not. `app/cli.py` imported fastgeoapi's settings at module level,
pydantic-settings built them eagerly, and the command died on two
missing variables before it had even looked at its arguments.

The test runs in a bare subprocess rather than in this one, because the
suite's own conftest sets those variables — checking the property here
would prove nothing.
"""

import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Imports the CLI, stands in for the server, and runs the command.
#: Everything inside runs with an environment that knows nothing about
#: fastgeoapi.
SCRIPT = """
import sys
from unittest import mock
from typer.testing import CliRunner

with mock.patch("uvicorn.run") as run:
    from app.cli import app
    result = CliRunner().invoke(app, ["config", "edit", "--source", sys.argv[1]])

if result.exit_code != 0:
    sys.stderr.write(result.output)
    raise SystemExit(result.exception or "the command failed")
if not run.called:
    raise SystemExit("nothing was served")
served = run.call_args[0][0]
if not hasattr(served.state, "editor_token"):
    raise SystemExit("that is not the authoring application")

# And the part that is actually worth having: a dry run builds the whole
# API and reads each source. Nothing upstream offers it, and it is the
# reason someone with only pygeoapi would install this.
from starlette.testclient import TestClient
from app.editor.app import EDITOR_TOKEN_HEADER

with TestClient(served) as client:
    client.headers[EDITOR_TOKEN_HEADER] = served.state.editor_token
    document = client.get("/editor/config").json()["document"]
    outcome = client.post("/editor/dry-run", json={"document": document}).json()

if not outcome.get("ok"):
    raise SystemExit(f"the dry run failed: {outcome}")
if "lakes" not in outcome.get("collections", []):
    raise SystemExit(f"nothing was built: {outcome}")
print("ok")
"""


def _bare(where: Path, *args: str) -> subprocess.CompletedProcess:
    """Run in an environment — and a directory — holding nothing of ours.

    The directory matters as much as the environment: pydantic-settings
    reads a `.env` from the working directory, so a subprocess started
    in the repository picks up the one committed there and the test
    passes without proving anything. This one starts somewhere empty.
    """
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [sys.executable, "-c", SCRIPT, *args],
        cwd=where,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def plain_config(tmp_path) -> Path:
    """A pygeoapi configuration with no fastgeoapi anything in it."""
    source = Path("tests/data/pygeoapi-config.yml").read_text()
    # A plain pygeoapi document resolves its own placeholders or has
    # none; ours carries the ones fastgeoapi's runner exports.
    for name, value in (
        ("${HOST}", "0.0.0.0"),
        ("${PORT}", "5000"),
        ("${PYGEOAPI_BASEURL}", "http://localhost:5000"),
        ("${FASTGEOAPI_CONTEXT}", ""),
    ):
        source = source.replace(name, value)
    # Absolute: the subprocess starts in an empty directory, so the
    # suite's relative paths would point at nothing there.
    source = source.replace("tests/data/", f"{REPO}/tests/data/")
    target = tmp_path / "pygeoapi-config.yml"
    target.write_text(source)
    return target


def test_the_editor_runs_without_fastgeoapi_being_configured(plain_config):
    """No HOST, no PORT, no .env — and it still opens the document."""
    result = _bare(plain_config.parent, str(plain_config))

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout, result.stdout


def test_the_settings_are_not_imported_to_reach_the_editor(plain_config):
    """The rule behind the test above, stated so it cannot rot quietly.

    A module-level import of the settings is the thing that broke this,
    and it is the kind of line somebody adds back without noticing —
    it costs nothing until the day someone without a `.env` runs the
    command.
    """
    probe = (
        "import sys;"
        " import app.cli;"
        " print('imported' if 'app.config.app' not in sys.modules else 'settings were built')"
    )
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [sys.executable, "-c", probe],
        cwd=plain_config.parent,
        env={"PATH": "/usr/bin:/bin", "HOME": "/tmp", "PYTHONPATH": str(REPO)},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout, result.stdout
