#!/usr/bin/env python
"""Generate the Pydantic models for pygeoapi's configuration schema.

Run through nox, which is where the generator is installed:

    nox -s models              # regenerate
    nox -s models -- --check   # fail if the committed files are stale

Three artefacts are written together, on purpose — they are three views
of one fact, and letting them drift apart is the failure this guards
against:

- ``_generated.py``  the models
- ``pygeoapi-config-schema.yml``  a copy of the schema they came from
- ``schema_digest.py``  its fingerprint

The copy is what makes a future change reviewable. A digest alone says
*that* the schema moved; the copy says *what* moved, property by
property, which is what a changelog entry needs to be worth reading.
"""

import filecmp
import hashlib
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import pygeoapi
import typer
from rich.console import Console

log_console = Console(stderr=True)
err_console = Console(stderr=True, style="bold red")

app = typer.Typer(add_completion=False)

PACKAGE = Path("app/pygeoapi/config_models")
GENERATED = PACKAGE / "_generated.py"
SCHEMA_COPY = PACKAGE / "pygeoapi-config-schema.yml"
DIGEST = PACKAGE / "schema_digest.py"

DIGEST_TEMPLATE = '''"""Identity of the schema the models were generated from.

Written by `scripts/generate_config_models.py`; do not edit by hand.

pygeoapi's schema carries no version — its `$id` points at master — so
content is the only identity available. `tests/test_config_models_drift.py`
compares this against the installed schema and goes red when they part.
"""

from pathlib import Path

#: sha256 of the schema at generation time.
SCHEMA_SHA256 = "{digest}"

#: pygeoapi version that shipped it, for the changelog entry.
PYGEOAPI_VERSION = "{version}"

#: The copy kept beside the models, so a change can be diffed.
SCHEMA_PATH = Path(__file__).parent / "{copy_name}"
'''


def _installed_schema() -> Path:
    return Path(pygeoapi.__file__).parent / "resources/schemas/config/pygeoapi-config-0.x.yml"


def _generate_models(schema: Path, target: Path) -> None:
    """Run the generator.

    Two flags carry weight here.

    `--disable-timestamp`: without it two runs of the same generator
    differ by a header comment, so every regeneration would look like a
    change and `--check` could never pass.

    `--extra-fields=allow`: the faithful translation of the schema.
    pygeoapi declares no `additionalProperties`, and JSON Schema's
    default is permissive — so a model that drops unknown keys is
    *stricter than the schema it claims to represent*. It also matters
    concretely: `store_options` and `engine_options` are ours, absent
    from the schema, and the default `ignore` accepted them and threw
    them away without a word. A model that discards in silence is worse
    than one that refuses.

    `--use-annotated`: emits `Annotated[str, StringConstraints(...)]`
    instead of `constr(...)`, which is a function call sitting in a type
    expression — valid for pydantic, rejected by the type checker. It is
    also the form pydantic v2 is moving to.
    """
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [
            sys.executable,
            "-m",
            "datamodel_code_generator",
            "--input",
            str(schema),
            "--input-file-type",
            "jsonschema",
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--disable-timestamp",
            "--extra-fields",
            "allow",
            "--use-annotated",
            "--output",
            str(target),
        ],
        check=True,
    )


@app.command()
def generate(
    check: Annotated[
        bool,
        typer.Option("--check", help="Fail if the committed files are stale"),
    ] = False,
) -> None:
    """Regenerate the models, the schema copy and the digest."""
    import importlib.metadata as metadata

    schema = _installed_schema()
    digest = hashlib.sha256(schema.read_bytes()).hexdigest()
    version = metadata.version("pygeoapi")

    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "_generated.py"
        _generate_models(schema, fresh)

        if check:
            stale = [
                name
                for name, ok in (
                    ("models", GENERATED.exists() and filecmp.cmp(fresh, GENERATED, shallow=False)),
                    (
                        "schema copy",
                        SCHEMA_COPY.exists() and filecmp.cmp(schema, SCHEMA_COPY, shallow=False),
                    ),
                    ("digest", DIGEST.exists() and digest in DIGEST.read_text()),
                )
                if not ok
            ]
            if stale:
                err_console.print(
                    f"stale: {', '.join(stale)} — run `nox -s models` and commit the result"
                )
                raise typer.Exit(code=1)
            log_console.log("models, schema copy and digest are up to date")
            return

        PACKAGE.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fresh, GENERATED)
        shutil.copyfile(schema, SCHEMA_COPY)
        DIGEST.write_text(
            DIGEST_TEMPLATE.format(digest=digest, version=version, copy_name=SCHEMA_COPY.name)
        )

    classes = sum(1 for line in GENERATED.read_text().splitlines() if line.startswith("class "))
    log_console.log(f"generated {classes} models from pygeoapi {version} (sha256 {digest[:12]}…)")


if __name__ == "__main__":
    app()
