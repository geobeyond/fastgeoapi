"""Merging ingested resources into a configuration document someone already keeps.

The document changes only where the ingest changes it. A resource the
catalog changed is rewritten, a new one goes at the end of ``resources``, a
pruned one is removed, and every other line stays as it was: comments,
quotes and ``${VAR}`` placeholders included. ruamel.yaml reads the document
to find the lines of each resource, and the edits are made on the text,
since a round trip of the whole document rewrites more than the ingest
asks for, a description wrapped over several lines for one.
"""

from __future__ import annotations

import io
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.representer import RoundTripRepresenter
from ruamel.yaml.util import load_yaml_guess_indent

from fastgeoapi_portolan import geoparquet, tiles
from fastgeoapi_portolan.catalog.locations import root_document
from fastgeoapi_portolan.reader import Skipped
from fastgeoapi_portolan.resources import Built

# The keys of a resource the ingest owns; any other key is kept as written.
GENERATED = ("type", "title", "description", "keywords", "links", "extents", "providers", "ingest")
OUR_PROVIDERS = (geoparquet.PROVIDER, tiles.PROVIDER)


class _Representer(RoundTripRepresenter):
    """Writes ``None`` as ``null``, as pygeoapi's configurations do."""


_Representer.add_representer(
    type(None),
    lambda representer, _: representer.represent_scalar("tag:yaml.org,2002:null", "null"),
)


@dataclass
class Merged:
    """The merged document, and what the merge did to its resources."""

    text: str
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)


def _yaml(mapping: int = 2, sequence: int = 4, offset: int = 2) -> YAML:
    yaml = YAML()
    yaml.Representer = _Representer
    yaml.preserve_quotes = True
    # ruamel.yaml would wrap long values at 80 columns.
    yaml.width = 4096
    yaml.indent(mapping=mapping, sequence=sequence, offset=offset)
    return yaml


def _yaml_like(text: str) -> YAML:
    """A YAML that writes with the indentation of ``text``."""
    if not text.strip():
        return _yaml()
    _, indent, block_seq_indent = load_yaml_guess_indent(text)
    if not block_seq_indent:
        return _yaml(mapping=indent or 2)
    return _yaml(mapping=indent - block_seq_indent, sequence=indent, offset=block_seq_indent)


def _plain(node: Any) -> Any:
    """``node`` as dicts, lists and plain scalars, for comparing with what the ingest built."""
    if isinstance(node, Mapping):
        return {str(key): _plain(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_plain(value) for value in node]
    if isinstance(node, str):
        return str(node)
    if isinstance(node, bool):
        return bool(node)
    if isinstance(node, int):
        return int(node)
    if isinstance(node, float):
        return float(node)
    return node


def _render(yaml: YAML, resources: Mapping[str, Any]) -> list[str]:
    out = io.StringIO()
    yaml.dump({"resources": dict(resources)}, out)
    return out.getvalue().splitlines(keepends=True)


def render(built: Sequence[Built]) -> str:
    """A YAML document holding the ``resources`` of ``built`` and nothing else."""
    return "".join(_render(_yaml(), {entry.id: entry.resource for entry in built}))


def _ours(resource: Any, root: str) -> dict[str, Any] | None:
    """The provenance of ``resource`` when it was ingested from the catalog at ``root``."""
    ingest = resource.get("ingest") if isinstance(resource, dict) else None
    if not isinstance(ingest, dict) or ingest.get("from") != "portolan":
        return None
    catalog = ingest.get("catalog")
    if not isinstance(catalog, str) or root_document(catalog) != root:
        return None
    return ingest


def _updated(current: dict[str, Any], built: Mapping[str, Any]) -> dict[str, Any]:
    """``current`` with the generated keys of ``built``; the other keys stay."""
    result: dict[str, Any] = {}
    for key, value in current.items():
        if key == "providers":
            others = [
                provider
                for provider in value or []
                if not (isinstance(provider, dict) and provider.get("name") in OUR_PROVIDERS)
            ]
            result[key] = [*built.get("providers", []), *others]
        elif key in GENERATED:
            if key in built:
                result[key] = built[key]
        else:
            result[key] = value
    for key in GENERATED:
        if key in built and key not in result:
            result[key] = built[key]
    return result


def _is_trailing(line: str, column: int) -> bool:
    """Whether ``line`` belongs to what follows a block whose keys sit at ``column``."""
    stripped = line.strip()
    indent = len(line) - len(line.lstrip())
    return not stripped or (stripped.startswith("#") and indent <= column)


class _Layout:
    """Where ``resources`` and each resource sit in the lines of the document."""

    def __init__(self, data: Any, lines: list[str]) -> None:
        self.lines = lines
        self.resources = CommentedMap()
        self.key_line: int | None = None
        self.end = len(lines)
        if not isinstance(data, CommentedMap) or "resources" not in data:
            return
        keys = list(data)
        self.key_line = data.lc.key("resources")[0]
        following = keys[keys.index("resources") + 1 :]
        self.end = data.lc.key(following[0])[0] if following else len(lines)
        while self.end > self.key_line + 1 and _is_trailing(lines[self.end - 1], 0):
            self.end -= 1
        if isinstance(data["resources"], CommentedMap):
            self.resources = data["resources"]

    def block(self, resource_id: str) -> tuple[int, int]:
        """The lines of a resource, without the blank lines and comments after it."""
        ids = list(self.resources)
        start, column = self.resources.lc.key(resource_id)
        position = ids.index(resource_id)
        stop = self.resources.lc.key(ids[position + 1])[0] if position + 1 < len(ids) else self.end
        while stop > start + 1 and _is_trailing(self.lines[stop - 1], column):
            stop -= 1
        return start, stop


def merge(
    text: str,
    built: Sequence[Built],
    *,
    catalog: str,
    selected: frozenset[str] | None,
    prune: bool,
    still_listed: frozenset[str] = frozenset(),
) -> Merged:
    """Merge the resources of ``built``, ingested from ``catalog``, into the document ``text``.

    A resource ingested from the same catalog and collection is updated
    key by key; one written by hand, or ingested from elsewhere, is left
    alone and reported as skipped. A resource of this catalog whose
    collection was not built is missing, unless the catalog still lists it
    (``still_listed``) or ``selected`` leaves it out; with ``prune`` a
    missing resource is removed instead of reported.
    """
    yaml = _yaml_like(text)
    lines = text.splitlines(keepends=True)
    layout = _Layout(yaml.load(text) if text.strip() else None, lines)
    root = root_document(catalog)
    merged = Merged(text)
    edits: list[tuple[int, int, list[str]]] = []
    added: dict[str, Any] = {}

    for entry in built:
        if entry.id not in layout.resources:
            added[entry.id] = entry.resource
            merged.added.append(entry.id)
            continue
        current = _plain(layout.resources[entry.id])
        ingest = current.get("ingest") if isinstance(current, dict) else None
        if not isinstance(ingest, dict):
            reason = f"the configuration has a resource {entry.id} written by hand: left alone"
            merged.skipped.append(Skipped(entry.id, reason))
            continue
        if (
            _ours(current, root) is None
            or ingest.get("collection") != entry.resource["ingest"]["collection"]
        ):
            reason = (
                f"the resource {entry.id} comes from {ingest.get('catalog')}, "
                f"collection {ingest.get('collection')}: left alone"
            )
            merged.skipped.append(Skipped(entry.id, reason))
            continue
        updated = _updated(current, entry.resource)
        if updated != current:
            start, stop = layout.block(entry.id)
            edits.append((start, stop, _render(yaml, {entry.id: updated})[1:]))
            merged.updated.append(entry.id)

    built_collections = {entry.resource["ingest"]["collection"] for entry in built}
    for resource_id, node in layout.resources.items():
        ingest = _ours(_plain(node), root)
        if ingest is None:
            continue
        collection = ingest.get("collection")
        if collection in built_collections or collection in still_listed:
            continue
        if selected is not None and collection not in selected:
            continue
        if prune:
            start, stop = layout.block(resource_id)
            edits.append((start, stop, []))
            merged.pruned.append(resource_id)
        else:
            merged.missing.append(resource_id)

    if added:
        rendered = _render(yaml, added)
        if layout.key_line is None:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            edits.append((len(lines), len(lines), rendered))
        elif not layout.resources:
            edits.append((layout.key_line, layout.key_line + 1, rendered))
        else:
            edits.append((layout.end, layout.end, rendered[1:]))

    for start, stop, replacement in sorted(edits, key=lambda edit: edit[0], reverse=True):
        lines[start:stop] = replacement
    merged.text = "".join(lines)
    return merged
