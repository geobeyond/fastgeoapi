"""The names of the tools generated from our OpenAPI document.

FastMCP names a tool after the operationId and cuts the name at 56
characters. pygeoapi takes the ids of the tileset operations from OGC
API - Tiles and puts the collection in front, which on the demo gives
``describeOverture-places-tiles.collection.vector.getTileSetsList``.
With a collection id that long the list of tilesets and the single
tileset share their first 56 characters, and FastMCP tells them apart
only by adding ``_2`` to the second. This module names the two on the
model of ``get<Collection>Features`` and ``get<Collection>Feature``.
Every ``FastMCP.from_openapi`` in the codebase uses these names, like
the route maps.
"""

from __future__ import annotations

import re

from loguru import logger
from openapi_pydantic.v3.v3_0 import OpenAPI, Operation

from app.mcp.route_maps import TILE_DATA_PATTERN

MAX_NAME_LENGTH = 56
"""Where FastMCP cuts a tool name (``_generate_default_name``, 4.0.3)."""

_TILESETS = re.compile(
    r"^describe(?P<collection>.+)\.collection\.\w+\.(?P<operation>getTileSetsList|getTileSet)$"
)
_SUFFIXES = {"getTileSetsList": "TileSets", "getTileSet": "TileSet"}


def _slug(text: str) -> str:
    """The name FastMCP makes of an operationId, before it cuts it."""
    slug = re.sub(r"[\s\-\.]+", "_", text)
    slug = re.sub(r"[^a-zA-Z0-9_]", "", slug)
    return re.sub(r"_+", "_", slug).strip("_")


def tool_names(openapi_spec: dict) -> dict[str, str]:
    """The ``mcp_names`` to pass to ``FastMCP.from_openapi``.

    Only the tileset operations are renamed. Their name leaves out the
    tile type (``vector``, ``map``) because pygeoapi gives a collection
    one tile provider. Any other name that is still too long is logged,
    since FastMCP cuts it without saying so. The tile data operation is
    left out of that check: it never becomes a tool.
    """
    openapi = OpenAPI.model_validate(openapi_spec)
    names: dict[str, str] = {}
    for path, item in openapi.paths.items():
        for operation in dict(item).values():
            if not isinstance(operation, Operation) or not operation.operationId:
                continue
            operation_id = operation.operationId
            match = _TILESETS.match(operation_id)
            if match:
                names[operation_id] = f"get{match['collection']}{_SUFFIXES[match['operation']]}"
            name = _slug(names.get(operation_id, operation_id.split("__")[0]))
            if len(name) > MAX_NAME_LENGTH and not re.match(TILE_DATA_PATTERN, path):
                logger.warning(
                    f"MCP tool name {name!r} (operation {operation_id!r}) is longer than "
                    f"{MAX_NAME_LENGTH} characters and FastMCP cuts it to "
                    f"{name[:MAX_NAME_LENGTH]!r}"
                )
    return names
