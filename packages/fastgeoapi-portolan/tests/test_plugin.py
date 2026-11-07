"""``portolan fastgeoapi ingest``: the command as a plugin of portolan-cli."""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner
from ruamel.yaml import YAML

from fastgeoapi_portolan.catalog.testing import write_fixtures
from fastgeoapi_portolan.plugin import command


def test_the_plugin_is_a_group_named_fastgeoapi():
    assert isinstance(command, click.Group)
    assert command.name == "fastgeoapi"
    assert list(command.commands) == ["ingest"]


def test_portolan_runs_the_ingest(tmp_path):
    portolan_cli = pytest.importorskip("portolan_cli")
    # Command plugins arrived after portolan-cli 1.0.0b0.
    pytest.importorskip("portolan_cli.plugins.commands")
    fixtures = write_fixtures(tmp_path)

    result = CliRunner().invoke(
        portolan_cli.cli,
        ["fastgeoapi", "ingest", "--from-portolan", str(fixtures.alternate_assets)],
    )

    assert result.exit_code == 0, result.output
    assert list(YAML(typ="safe").load(result.stdout)["resources"]) == ["bathymetry"]
