"""The document's tag list, derived from the document's own operations.

pygeoapi's API modules each return a module-level tag object whether or
not they contribute a path, and the guard that should drop them
(``pygeoapi/openapi.py:556``) reads ``if not sub_tags and not
sub_paths`` — a conjunction, so a module with tags and no paths is never
skipped. The module tags are then never used either, because operations
are tagged with the id of the collection or process they serve.

Measured on the demo (2026-09-15): fifteen declared tags, eight of them
with no operation and no description.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pygeoapi.util import yaml_load


@pytest.fixture(scope="module")
def config_dict() -> dict:
    return yaml_load(Path("tests/data/pygeoapi-config.yml").open())


def _document() -> dict:
    """A document shaped like pygeoapi's: two tags nobody uses."""
    return {
        "tags": [
            {"name": "server", "description": "the server"},
            {"name": "obs", "description": "my cool observations"},
            {"name": "coverages"},
            {"name": "features"},
        ],
        "paths": {
            "/": {
                "get": {"tags": ["server"], "responses": {}},
            },
            "/collections/obs/items": {
                "get": {"tags": ["obs"], "responses": {}},
                "options": {"tags": ["obs"], "responses": {}},
                "parameters": [{"name": "f", "in": "query"}],
                "summary": "not an operation",
            },
        },
    }


def test_a_tag_no_operation_uses_is_dropped():
    from app.pygeoapi.openapi import drop_unused_tags

    doc = drop_unused_tags(_document())

    assert [tag["name"] for tag in doc["tags"]] == ["server", "obs"]


def test_a_used_tag_keeps_its_description_and_its_place():
    from app.pygeoapi.openapi import drop_unused_tags

    doc = drop_unused_tags(_document())

    assert doc["tags"][1] == {"name": "obs", "description": "my cool observations"}


def test_what_is_not_an_operation_does_not_keep_a_tag_alive():
    """A path item also holds ``parameters`` and ``summary``.

    Reading them as operations would be harmless here and wrong
    elsewhere: a ``parameters`` list has no ``tags`` member, but a
    ``get`` that is a string ``$ref`` would raise.
    """
    from app.pygeoapi.openapi import drop_unused_tags

    doc = _document()
    doc["paths"]["/collections/obs/items"]["$ref"] = "#/components/pathItems/items"

    assert [tag["name"] for tag in drop_unused_tags(doc)["tags"]] == ["server", "obs"]


def test_a_document_without_tags_is_left_alone():
    from app.pygeoapi.openapi import drop_unused_tags

    assert drop_unused_tags({"paths": {}}) == {"paths": {}}


def test_the_built_document_declares_no_tag_it_does_not_use(config_dict):
    """The end to end: what `build_openapi` hands to a consumer."""
    from app.pygeoapi.factory import build_openapi

    doc = build_openapi(config_dict)
    used = {
        tag
        for item in doc["paths"].values()
        for operation in item.values()
        if isinstance(operation, dict)
        for tag in operation.get("tags", [])
    }
    declared = [tag["name"] for tag in doc["tags"]]

    assert [name for name in declared if name not in used] == []
