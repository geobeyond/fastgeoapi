"""Test cases for the cli module."""
from cli import app
from typer.testing import CliRunner


def test_openapi_succeeds(runner: CliRunner) -> None:
    """It exits with a status code of zero."""
    result = runner.invoke(app, ["openapi"])
    assert result.exit_code == 0
