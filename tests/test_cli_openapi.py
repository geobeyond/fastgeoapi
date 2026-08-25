"""The openapi command generates the document from the storage source.

The URL case is the discriminating one: the old code ran ``open()`` on
the value, so any storage-layer URL has to go through ``load_store``.
"""

import json
import sys
from pathlib import Path

from typer.testing import CliRunner


def test_openapi_command_writes_document_from_source(tmp_path, monkeypatch):
    src = tmp_path / "pygeoapi-config.yml"
    src.write_text(Path("tests/data/pygeoapi-config.yml").read_text())
    out = tmp_path / "pygeoapi-openapi.yml"
    monkeypatch.setenv("DEV_PYGEOAPI_CONFIG", str(src))
    monkeypatch.setenv("DEV_PYGEOAPI_OPENAPI", str(out))

    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    from app.cli import app as cli_app

    result = CliRunner().invoke(cli_app, ["openapi"])
    assert result.exit_code == 0, result.output
    # Historical contract of the command: enriched JSON artifact next
    # to the configured path (.json suffix).
    doc = json.loads(out.with_suffix(".json").read_text())
    assert "/collections" in doc["paths"]


def test_openapi_command_reads_config_from_url_source(tmp_path, monkeypatch):
    """The source can be a storage-layer URL, not just a file.

    ``file://`` walks exactly the remote-scheme code path
    (``load_store`` → obstore): if it works here, it works with
    ``s3://`` up to credentials. The old command ran ``open()`` on the
    value and blew up on any URL.
    """
    src = tmp_path / "pygeoapi-config.yml"
    src.write_text(Path("tests/data/pygeoapi-config.yml").read_text())
    out = tmp_path / "pygeoapi-openapi.yml"
    monkeypatch.setenv("DEV_PYGEOAPI_CONFIG", f"file://{src}")
    monkeypatch.setenv("DEV_PYGEOAPI_OPENAPI", str(out))

    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    from app.cli import app as cli_app

    result = CliRunner().invoke(cli_app, ["openapi"])
    assert result.exit_code == 0, result.output
    doc = json.loads(out.with_suffix(".json").read_text())
    assert "/collections" in doc["paths"]


def test_openapi_command_writes_to_url_target(tmp_path, monkeypatch):
    """The output target goes through the storage Protocol as well.

    With a ``file://`` target the old ``Path(...).with_suffix()`` route
    would mangle the URL into a relative path under cwd.
    """
    src = tmp_path / "pygeoapi-config.yml"
    src.write_text(Path("tests/data/pygeoapi-config.yml").read_text())
    out = tmp_path / "out" / "pygeoapi-openapi.yml"
    out.parent.mkdir()
    monkeypatch.setenv("DEV_PYGEOAPI_CONFIG", str(src))
    monkeypatch.setenv("DEV_PYGEOAPI_OPENAPI", f"file://{out}")

    for key in list(sys.modules):
        if key.startswith("app."):
            del sys.modules[key]
    from app.config.app import FactoryConfig

    FactoryConfig.get_config.cache_clear()
    from app.cli import app as cli_app

    result = CliRunner().invoke(cli_app, ["openapi"])
    assert result.exit_code == 0, result.output
    doc = json.loads(out.with_suffix(".json").read_text())
    assert "/collections" in doc["paths"]
    # The security augmentation still applies.
    assert "securitySchemes" in doc["components"]
