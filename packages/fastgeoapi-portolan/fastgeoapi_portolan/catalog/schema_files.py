"""Where the copied JSON Schemas are, and the URLs they answer to."""

from __future__ import annotations

import json
from collections.abc import Iterator
from functools import reduce
from importlib.resources import files
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from importlib.abc import Traversable

_PACKAGE = "fastgeoapi_portolan.catalog.schemas"
_STAC = "https://schemas.stacspec.org/v"
_PORTOLAN = "https://schemas.portolan-sdi.org/portolan/"


def _relative(url: str) -> str | None:
    url = url.split("#", 1)[0]
    if url.startswith(_STAC):
        version, _, rest = url[len(_STAC) :].partition("/")
        return f"stac/{version}/{rest}"
    if url.startswith(_PORTOLAN):
        return f"portolan/{url[len(_PORTOLAN) :]}"
    scheme, _, rest = url.partition("://")
    return f"extensions/{rest}" if scheme == "https" and rest else None


def _url(relative: str) -> str | None:
    top, _, rest = relative.partition("/")
    if top == "stac":
        version, _, path = rest.partition("/")
        return f"{_STAC}{version}/{path}"
    if top == "portolan":
        return f"{_PORTOLAN}{rest}"
    if top == "extensions":
        return f"https://{rest}"
    return None


def schema_file(url: str) -> Traversable | None:
    """The copied file of the schema at ``url``, or ``None`` when there is none."""
    relative = _relative(url)
    if relative is None:
        return None
    found = reduce(lambda node, part: node.joinpath(part), relative.split("/"), files(_PACKAGE))
    return found if found.is_file() else None


def _documents(node: Traversable, prefix: str = "") -> Iterator[tuple[str, Traversable]]:
    for child in node.iterdir():
        path = f"{prefix}{child.name}"
        if child.is_dir():
            yield from _documents(child, f"{path}/")
        elif child.name.endswith(".json"):
            yield path, child


def schema_resources() -> list[tuple[str, dict[str, Any]]]:
    """Every copied schema, under the URL its path gives and under its ``$id``.

    Both names are needed: STAC 1.1.0's ``common.json`` declares the
    ``$id`` ``…/item-spec/json-schema/commonjson``, so a ``$ref`` to
    ``common.json`` finds it only by the URL of its path.
    """
    resources = []
    for relative, node in _documents(files(_PACKAGE)):
        contents = json.loads(node.read_text(encoding="utf-8"))
        if "$schema" not in contents and "$id" not in contents:
            continue
        urls = {_url(relative), str(contents.get("$id", "")).split("#", 1)[0] or None}
        resources += [(url, contents) for url in sorted(urls - {None})]
    return resources
