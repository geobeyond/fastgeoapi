"""fastgeoapi's own keys in a pygeoapi configuration.

pygeoapi's schema leaves the keys of a collection and of the server's map
open, so fastgeoapi can add its own and pygeoapi ignores them. They are
checked here, after pygeoapi's validation, and offered to the editor's form
by extending the schema it serves. There are two today: a collection's
``view``, where the maps of its HTML pages open when the data does not say,
and the ``style`` of the server's map, the MapLibre style those maps are drawn
on instead of the tiles of its ``url``.
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

MAP_STYLE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "description": (
        "A MapLibre style the maps of the HTML pages are drawn on, instead of the tiles of url"
    ),
    "pattern": "^https?://",
}

MAP_KEYS: dict[str, dict[str, Any]] = {"style": MAP_STYLE_SCHEMA}
"""fastgeoapi's keys of the server's map, with their schemas."""


def extend_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """pygeoapi's configuration schema with fastgeoapi's collection keys.

    ``schema`` itself is not changed.
    """
    extended = deepcopy(schema)
    for collection in _collection_schemas(extended):
        collection.setdefault("properties", {}).update(deepcopy(COLLECTION_KEYS))
    server = extended.get("properties", {}).get("server", {})
    server_map = server.get("properties", {}).get("map")
    if server_map is not None:
        server_map.setdefault("properties", {}).update(deepcopy(MAP_KEYS))
    return extended


def extension_problem(config: dict[str, Any]) -> tuple[str, str] | None:
    """Where the first of fastgeoapi's keys breaks its schema, and why; None when all hold."""
    server_map = (config.get("server") or {}).get("map")
    for key, schema in MAP_KEYS.items():
        if isinstance(server_map, dict) and key in server_map:
            problem = _problem(schema, server_map[key], ["server", "map", key])
            if problem is not None:
                return problem
    for name, resource in (config.get("resources") or {}).items():
        if not isinstance(resource, dict) or resource.get("type") != "collection":
            continue
        for key, schema in COLLECTION_KEYS.items():
            if key not in resource:
                continue
            problem = _problem(schema, resource[key], ["resources", name, key])
            if problem is not None:
                return problem
    return None


def _problem(schema: dict[str, Any], value: Any, where: list[str]) -> tuple[str, str] | None:
    """Where ``value`` first breaks ``schema``, below ``where``, and why."""
    error = best_match(Draft7Validator(schema).iter_errors(value))
    if error is None:
        return None
    path = [str(part) for part in error.absolute_path]
    return ".".join([*where, *path]), error.message


def _collection_schemas(schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """The schemas of a collection resource: the alternatives that have ``extents``."""
    resources = schema.get("properties", {}).get("resources", {})
    for pattern in (resources.get("patternProperties") or {}).values():
        for alternative in pattern.get("anyOf", [pattern]):
            if "extents" in alternative.get("properties", {}):
                yield alternative
