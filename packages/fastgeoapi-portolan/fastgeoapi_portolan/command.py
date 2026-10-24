"""The ingest command: from a Portolan catalog to the resources of a fastgeoapi configuration.

It is a click command so that portolan-cli can load it as a plugin.
fastgeoapi runs the same command under ``config``, so options, messages
and exit codes are the same in both. The caller gives the configuration
validator, which is looked up only when a document is about to be written.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, NoReturn

import click
from ruamel.yaml import YAMLError

from fastgeoapi_portolan.catalog.protocols import MAX_DOCUMENT_BYTES
from fastgeoapi_portolan.catalog.walk import MAX_DOCUMENTS, STOPPED_AT_LIMIT
from fastgeoapi_portolan.document import ConcurrentEditError, read_document, write_document
from fastgeoapi_portolan.handlers import Overrides, unreadable
from fastgeoapi_portolan.merge import Merged, merge, render
from fastgeoapi_portolan.reader import Catalog, Skipped, read_catalog
from fastgeoapi_portolan.resources import Built, DuplicateCollectionIdError, build

# Takes the text of a configuration document and returns its problems.
Validator = Callable[[str], list[str]]
VALIDATORS = "fastgeoapi_portolan.validators"
NOT_VALIDATED = "the document was not validated: no configuration validator is installed"
NOT_PRUNED = "nothing pruned: the walk did not read the whole catalog"


def discovered_validator() -> Validator | None:
    """The validator the first entry point of ``fastgeoapi_portolan.validators`` names.

    Nothing is imported until this is called; ``None`` when no installed
    package declares one.
    """
    found = list(entry_points(group=VALIDATORS))
    return found[0].load() if found else None


@dataclass(frozen=True)
class _Request:
    """What the command line asks for."""

    catalog: str
    into: str | None
    selected: frozenset[str] | None
    prefix: str
    overrides: Overrides
    prune: bool
    strict: bool
    as_json: bool


@dataclass
class _Outcome:
    """What the ingest did, for the summary."""

    catalog: Catalog
    built: list[Built]
    skipped: list[Skipped]
    warnings: list[str]
    merged: Merged | None = None


def _fail(message: str) -> NoReturn:
    click.echo(f"error: {message}", err=True)
    raise click.exceptions.Exit(1)


def _value(text: str) -> str | bool:
    """``true`` and ``false`` as booleans, as a configuration writes them; anything else as is."""
    lowered = text.lower()
    return lowered == "true" if lowered in ("true", "false") else text


def _pairs(
    values: Sequence[str],
    option: str,
    form: str,
    convert: Callable[[str], Any] = str,
) -> dict[str, Any]:
    pairs: dict[str, Any] = {}
    for value in values:
        key, equals, item = value.partition("=")
        if not equals or not key.strip():
            raise click.BadParameter(f"{value!r} is not {form}", param_hint=option)
        pairs[key.strip()] = convert(item.strip())
    return pairs


def _summary(request: _Request, outcome: _Outcome) -> dict[str, Any]:
    merged = outcome.merged
    left_alone = {entry.collection for entry in outcome.skipped}
    return {
        "catalog": outcome.catalog.root,
        "into": request.into,
        "added": merged.added if merged else [entry.id for entry in outcome.built],
        "updated": merged.updated if merged else [],
        "skipped": [
            {"collection": entry.collection, "reason": entry.reason} for entry in outcome.skipped
        ],
        "missing": merged.missing if merged else [],
        "pruned": merged.pruned if merged else [],
        "choices": {
            entry.id: list(entry.choices) for entry in outcome.built if entry.id not in left_alone
        },
        "warnings": outcome.warnings,
    }


def _text(summary: dict[str, Any]) -> str:
    lines = [f"catalog: {summary['catalog']}"]
    if summary["into"]:
        lines.append(f"into: {summary['into']}")
    for heading in ("added", "updated"):
        if summary[heading]:
            lines.append(f"{heading}:")
            for identifier in summary[heading]:
                lines.append(f"  {identifier}")
                lines.extend(f"    {choice}" for choice in summary["choices"].get(identifier, ()))
    if summary["skipped"]:
        lines.append("skipped:")
        lines.extend(f"  {entry['collection']}: {entry['reason']}" for entry in summary["skipped"])
    for key, heading in (("missing", "missing from the catalog, kept"), ("pruned", "pruned")):
        if summary[key]:
            lines.append(f"{heading}:")
            lines.extend(f"  {identifier}" for identifier in summary[key])
    if summary["warnings"]:
        lines.append("warnings:")
        lines.extend(f"  {warning}" for warning in summary["warnings"])
    return "\n".join(lines)


def _report(request: _Request, outcome: _Outcome) -> None:
    summary = _summary(request, outcome)
    text = json.dumps(summary, indent=2) if request.as_json else _text(summary)
    # Without --into the resources take stdout, so the summary goes to stderr.
    click.echo(text, err=request.into is None)


def _complete(catalog: Catalog) -> bool:
    """Whether the walk read every document the catalog links."""
    return not catalog.skipped and not any(
        warning.startswith(STOPPED_AT_LIMIT) for warning in catalog.warnings
    )


def _ingest(request: _Request) -> _Outcome:
    """Read the catalog and build its resources; an unreadable root or an id clash fails."""
    overrides = request.overrides
    try:
        catalog = asyncio.run(
            read_catalog(
                request.catalog,
                overrides.store_options,
                only=request.selected,
                max_documents=overrides.max_documents,
                max_bytes=overrides.max_document_bytes,
            )
        )
    except (OSError, ValueError) as error:
        _fail(f"{request.catalog} could not be read: {unreadable(error)}")
    try:
        built, skipped = asyncio.run(build(catalog, overrides, prefix=request.prefix))
    except DuplicateCollectionIdError as error:
        _fail(str(error))
    return _Outcome(catalog, built, skipped, list(catalog.warnings))


def _print(request: _Request, outcome: _Outcome) -> None:
    _report(request, outcome)
    if request.strict and outcome.skipped:
        _fail(f"--strict: {len(outcome.skipped)} collections skipped, nothing printed")
    click.echo(render(outcome.built), nl=False)


def _merge_into(
    request: _Request, outcome: _Outcome, validator: Callable[[], Validator | None]
) -> None:
    into = str(request.into)
    store_options = request.overrides.store_options
    try:
        document = read_document(into, store_options)
    except (OSError, ValueError) as error:
        _fail(f"{into} could not be read: {unreadable(error)}")
    # A collection the walk could not read may still be in the catalog.
    complete = _complete(outcome.catalog)
    try:
        merged = merge(
            document.text,
            outcome.built,
            catalog=outcome.catalog.root,
            selected=request.selected,
            prune=request.prune and complete,
            still_listed=frozenset(entry.collection for entry in outcome.skipped),
        )
    except YAMLError as error:
        _fail(f"{into} is not YAML: {' '.join(str(error).split())}")
    if request.prune and not complete:
        outcome.warnings.append(NOT_PRUNED)
    outcome.merged = merged
    outcome.skipped = [*outcome.skipped, *merged.skipped]

    if request.strict and outcome.skipped:
        _report(request, outcome)
        _fail(f"--strict: {len(outcome.skipped)} collections skipped, nothing written")
    if merged.text != document.text:
        check = validator()
        if check is None:
            outcome.warnings.append(NOT_VALIDATED)
        else:
            problems = check(merged.text)
            if problems:
                listed = "\n".join(f"  {problem}" for problem in problems)
                _fail(f"{into} would not be a valid configuration, nothing written:\n{listed}")
        try:
            write_document(document, merged.text, store_options)
        except ConcurrentEditError as error:
            _fail(str(error))
    _report(request, outcome)


def ingest_command(*, validator: Callable[[], Validator | None]) -> click.Command:
    """The ``ingest`` command; ``validator`` gives the configuration validator, if any."""

    @click.command("ingest")
    @click.option(
        "--from-portolan",
        "catalog",
        required=True,
        metavar="CATALOG",
        help="The catalog: its catalog.json or the folder that holds it, a path or a URL.",
    )
    @click.option(
        "--into",
        metavar="CONFIG",
        help="The configuration to merge the resources into, a path or a bucket URL. "
        "Without it, the resources are printed.",
    )
    @click.option(
        "--collection",
        "collections",
        multiple=True,
        metavar="ID",
        help="Ingest this collection only. Repeat for more.",
    )
    @click.option("--prefix", default="", help="Put this before every resource id.")
    @click.option(
        "--store-option",
        "store_options",
        multiple=True,
        metavar="KEY=VALUE",
        help="A storage option for the buckets, such as region, skip_signature or endpoint. "
        "Repeat for more.",
    )
    @click.option(
        "--id-field",
        "id_fields",
        multiple=True,
        metavar="COLLECTION=COLUMN",
        help="The id column of a collection, when the catalog names none. Repeat for more.",
    )
    @click.option(
        "--geometry-column",
        "geometry_columns",
        multiple=True,
        metavar="COLLECTION=COLUMN",
        help="The geometry column of a collection, when the catalog names none. Repeat for more.",
    )
    @click.option(
        "--check-ids",
        is_flag=True,
        help="Check that the id column has no duplicates, reading that column only.",
    )
    @click.option(
        "--prune",
        is_flag=True,
        help="With --into, remove the resources of this catalog whose collection is gone from it.",
    )
    @click.option("--strict", is_flag=True, help="Fail when a collection is skipped.")
    @click.option("--json", "as_json", is_flag=True, help="Print the summary as JSON.")
    @click.option(
        "--max-documents",
        type=click.IntRange(min=1),
        default=MAX_DOCUMENTS,
        show_default=True,
        help="The most documents the walk reads, and the most items read for a collection.",
    )
    @click.option(
        "--max-document-bytes",
        type=click.IntRange(min=1),
        default=MAX_DOCUMENT_BYTES,
        show_default=True,
        help="The largest document read, in bytes.",
    )
    def ingest(
        catalog: str,
        into: str | None,
        collections: tuple[str, ...],
        prefix: str,
        store_options: tuple[str, ...],
        id_fields: tuple[str, ...],
        geometry_columns: tuple[str, ...],
        check_ids: bool,
        prune: bool,
        strict: bool,
        as_json: bool,
        max_documents: int,
        max_document_bytes: int,
    ) -> None:
        """Read a Portolan catalog and write pygeoapi resources for its collections."""
        if check_ids:
            _fail("--check-ids needs duckdb: pip install duckdb")
        overrides = Overrides(
            store_options=_pairs(store_options, "--store-option", "key=value", _value),
            id_fields=_pairs(id_fields, "--id-field", "collection=column"),
            geometry_columns=_pairs(geometry_columns, "--geometry-column", "collection=column"),
            max_documents=max_documents,
            max_document_bytes=max_document_bytes,
        )
        request = _Request(
            catalog=catalog,
            into=into,
            selected=frozenset(collections) if collections else None,
            prefix=prefix,
            overrides=overrides,
            prune=prune,
            strict=strict,
            as_json=as_json,
        )
        outcome = _ingest(request)
        if into is None:
            _print(request, outcome)
        else:
            _merge_into(request, outcome, validator)

    return ingest
