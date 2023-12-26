"""Test cases for the cli module."""
import pytest
from cli import app
from typer.testing import CliRunner


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()


def test_openapi_succeeds(runner: CliRunner) -> None:
    """It exits with a status code of zero."""
    result = runner.invoke(app, ["openapi"])
    assert result.exit_code == 0
