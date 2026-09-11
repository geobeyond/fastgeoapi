"""Which OpenAPI operations become MCP tools (ADR-0011, decision 8).

A tile is a binary blob a model cannot use; the tilesets list and the
TileJSON are what an agent needs to discover a tile service. One list,
shared by every ``FastMCP.from_openapi`` in the codebase, so the three
servers we build (runtime, reload, editor preview) agree.
"""

from fastmcp.server.providers.openapi import MCPType, RouteMap

TILE_DATA_PATTERN = r".*/tiles/\{tileMatrixSetId\}/\{tileMatrix\}/\{tileRow\}/\{tileCol\}$"
"""pygeoapi's tile-data path template, as it appears in the OpenAPI document."""


def openapi_route_maps() -> list[RouteMap]:
    """The route maps every MCP server built from our OpenAPI document uses."""
    return [RouteMap(pattern=TILE_DATA_PATTERN, mcp_type=MCPType.EXCLUDE)]
