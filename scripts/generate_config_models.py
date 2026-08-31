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
REFERENCE = Path("docs/operators/reference/configuration.md")
ADDITIONS = Path("scripts/config_reference_additions.md")

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


def _properties(node: dict, prefix: str = "") -> dict[str, dict]:
    """Flatten a schema into `path -> spec`, for rendering and diffing."""
    found: dict[str, dict] = {}
    for name, spec in (node.get("properties") or {}).items():
        path = f"{prefix}.{name}" if prefix else name
        found[path] = spec
        if isinstance(spec, dict):
            found.update(_properties(spec, path))
    return found


def _required(node: dict, prefix: str = "") -> set[str]:
    """Every property path a schema marks as required, at any depth."""
    paths: set[str] = set()
    for name in node.get("required") or []:
        paths.add(f"{prefix}.{name}" if prefix else name)
    for name, spec in (node.get("properties") or {}).items():
        if isinstance(spec, dict):
            paths |= _required(spec, f"{prefix}.{name}" if prefix else name)
    return paths


def _render_reference(schema: dict, version: str) -> str:
    """Build the configuration reference from the schema's own text.

    The descriptions belong to pygeoapi (MIT), so the page says so: this
    republishes their documentation, and attribution is the least it
    owes them.
    """
    lines = [
        "# Configuration reference",
        "",
        "Every key fastgeoapi accepts in the pygeoapi configuration document.",
        "",
        '!!! info "Where this comes from"',
        "",
        f"    The tables below are generated from pygeoapi {version}'s own",
        "    configuration schema, descriptions included — that text is",
        "    pygeoapi's, published under the MIT licence. Regenerate with",
        "    `nox -s models`.",
        "",
    ]
    for section in schema.get("properties", {}):
        node = schema["properties"][section]
        required = set(node.get("required") or [])
        lines += [f"## `{section}`", ""]
        if node.get("description"):
            lines += [node["description"], ""]
        rows = [
            (path, spec)
            for path, spec in _properties(node, section).items()
            if isinstance(spec, dict) and spec.get("description")
        ]
        if not rows:
            lines += ["_No documented keys._", ""]
            continue
        lines += ["| Key | Type | Required | Description |", "| --- | --- | --- | --- |"]
        for path, spec in rows:
            leaf = path.split(".")[-1]
            mark = "yes" if leaf in required and path.count(".") == 1 else ""
            kind = spec.get("type", "")
            text = " ".join(str(spec["description"]).split())
            lines.append(f"| `{path}` | {kind} | {mark} | {text} |")
        lines.append("")
    if ADDITIONS.exists():
        lines += [ADDITIONS.read_text().strip(), ""]
    return "\n".join(lines)


def _summarise_changes(previous: dict, current: dict) -> list[str]:
    """What a user with a running configuration needs to check.

    Removals and narrowings come first: they are the only ones that can
    break a configuration that works today, and at 0.x the version
    number cannot tell them apart from additions.
    """
    was, now = _properties(previous), _properties(current)
    removed = sorted(set(was) - set(now))
    added = sorted(set(now) - set(was))
    retyped = sorted(
        path for path in set(was) & set(now) if was[path].get("type") != now[path].get("type")
    )
    # A property that already existed, unchanged in type, but is now
    # listed in `required` breaks every configuration that omitted it —
    # as hard as a removal, and with nothing else to signal it. Comparing
    # types alone misses this entirely.
    tightened = sorted(_required(current) - _required(previous))

    summary: list[str] = []
    for path in removed:
        summary.append(f"- **`{path}` is no longer accepted** — remove it from your configuration")
    for path in tightened:
        summary.append(f"- **`{path}` is now required** — add it if your configuration omits it")
    for path in retyped:
        summary.append(
            f"- **`{path}` changed type**: {was[path].get('type')} -> {now[path].get('type')}"
        )
    for path in added:
        summary.append(f"- `{path}` is now available")
    return summary


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
                    ("reference page", REFERENCE.exists()),
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

        # The summary has to be computed BEFORE the copy is overwritten:
        # afterwards there is nothing left to compare against, which is
        # the whole reason a copy is kept beside the digest.
        if SCHEMA_COPY.exists():
            import yaml

            changes = _summarise_changes(
                yaml.safe_load(SCHEMA_COPY.read_text()),
                yaml.safe_load(schema.read_text()),
            )
            if changes:
                log_console.print("\n[bold]For the changelog:[/bold]")
                for line in changes:
                    log_console.print(f"  {line}")
                log_console.print("")

        PACKAGE.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(fresh, GENERATED)
        shutil.copyfile(schema, SCHEMA_COPY)
        DIGEST.write_text(
            DIGEST_TEMPLATE.format(digest=digest, version=version, copy_name=SCHEMA_COPY.name)
        )

    import yaml

    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(_render_reference(yaml.safe_load(schema.read_text()), version))
    log_console.log(f"wrote {REFERENCE}")

    classes = sum(1 for line in GENERATED.read_text().splitlines() if line.startswith("class "))
    log_console.log(f"generated {classes} models from pygeoapi {version} (sha256 {digest[:12]}…)")


if __name__ == "__main__":
    app()
