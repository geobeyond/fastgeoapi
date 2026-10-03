"""fastgeoapi's own keys in a pygeoapi configuration.

pygeoapi's schema leaves the keys of a collection open, so fastgeoapi can
add its own and pygeoapi ignores them. They are checked here, after
pygeoapi's validation, and offered to the editor's form by extending the
schema it serves. There is one today: a collection's ``view``, where the
maps of its HTML pages open when the data does not say.
"""

from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import best_match

VIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "Where the maps of the collection's HTML pages open, when the data does not say",
    "properties": {
        "center": {
            "type": "array",
            "description": "Longitude and latitude, in degrees",
            "items": [
                {"type": "number", "minimum": -180, "maximum": 180},
                {"type": "number", "minimum": -90, "maximum": 90},
            ],
            "minItems": 2,
            "maxItems": 2,
            "additionalItems": False,
        },
        "zoom": {
            "type": "number",
            "description": "The zoom level, as in WebMercatorQuad",
            "minimum": 0,
            "maximum": 24,
        },
    },
    "required": ["center", "zoom"],
    "additionalProperties": False,
}

COLLECTION_KEYS: dict[str, dict[str, Any]] = {"view": VIEW_SCHEMA}
"""fastgeoapi's keys of a collection, with their schemas."""


def extend_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """pygeoapi's configuration schema with fastgeoapi's collection keys.

    ``schema`` itself is not changed.
    """
    extended = deepcopy(schema)
    for collection in _collection_schemas(extended):
        collection.setdefault("properties", {}).update(deepcopy(COLLECTION_KEYS))
    return extended


def extension_problem(config: dict[str, Any]) -> tuple[str, str] | None:
    """Where the first of fastgeoapi's keys breaks its schema, and why; None when all hold."""
    for name, resource in (config.get("resources") or {}).items():
        if not isinstance(resource, dict) or resource.get("type") != "collection":
            continue
        for key, schema in COLLECTION_KEYS.items():
            if key not in resource:
                continue
            error = best_match(Draft7Validator(schema).iter_errors(resource[key]))
            if error is not None:
                path = [str(part) for part in error.absolute_path]
                return ".".join(["resources", name, key, *path]), error.message
    return None


def _collection_schemas(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """The schemas of a collection resource: the alternatives that have ``extents``."""
    resources = schema.get("properties", {}).get("resources", {})
    for pattern in (resources.get("patternProperties") or {}).values():
        for alternative in pattern.get("anyOf", [pattern]):
            if "extents" in alternative.get("properties", {}):
                yield alternative
