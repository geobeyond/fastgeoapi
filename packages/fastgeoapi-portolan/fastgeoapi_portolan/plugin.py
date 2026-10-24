"""``portolan fastgeoapi``: the ingest command as a plugin of portolan-cli.

portolan-cli loads ``command`` through its ``portolan.commands`` entry
point and adds it next to its own commands.
"""

from __future__ import annotations

import click

from fastgeoapi_portolan.command import discovered_validator, ingest_command


@click.group(name="fastgeoapi")
def command() -> None:
    """Write fastgeoapi configurations from Portolan catalogs."""


command.add_command(ingest_command(validator=discovered_validator))
