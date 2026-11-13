"""The MCP tools that return the map of a collection as an image.

The tools generated from the OpenAPI document cannot carry an image:
FastMCP turns a response that is not JSON into text. So the map paths
are left out of that generation, and each map collection gets a tool
here that calls the same route through the same in-process client and
hands the PNG back as MCP image content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated

import httpx2
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.tools import Tool
from fastmcp.utilities.types import Image
from mcp.types import ToolAnnotations
from pydantic import Field

from app.mcp.names import fastmcp_name

MAP_PATH = re.compile(r"^/collections/(?P<collection>[^/]+)/map$")
DEFAULT_SIZE = 512
MAX_SIZE = 1024


@dataclass(frozen=True)
class MapCollection:
    """A collection that serves maps, as the document describes it."""

    collection_id: str
    title: str
    styles: tuple[str, ...]


def _title(paths: dict, collection_id: str) -> str:
    summary = ((paths.get(f"/collections/{collection_id}") or {}).get("get") or {}).get(
        "summary"
    ) or ""
    if summary.startswith("Get ") and summary.endswith(" metadata"):
        return summary.removeprefix("Get ").removesuffix(" metadata")
    return collection_id


def _styles(paths: dict, collection_id: str) -> tuple[str, ...]:
    styled = (paths.get(f"/collections/{collection_id}/styles/{{styleId}}/map") or {}).get("get")
    for parameter in (styled or {}).get("parameters", []):
        if isinstance(parameter, dict) and parameter.get("name") == "styleId":
            return tuple((parameter.get("schema") or {}).get("enum") or ())
    return ()


def map_collections(openapi_spec: dict) -> list[MapCollection]:
    """The collections the document gives a map path, with their title and styles."""
    paths = openapi_spec.get("paths", {})
    found = []
    for path in paths:
        match = MAP_PATH.match(path)
        if match:
            collection_id = match["collection"]
            found.append(
                MapCollection(
                    collection_id, _title(paths, collection_id), _styles(paths, collection_id)
                )
            )
    return found


def _message(response: httpx2.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"{response.status_code}: {response.text[:200]}"
    return f"{response.status_code}: {body.get('description', body)}"


def _map_tool(collection: MapCollection, client: httpx2.AsyncClient) -> Tool:
    base = f"/collections/{collection.collection_id}"
    style_help = f" Styles: {', '.join(collection.styles)}." if collection.styles else ""

    async def get_map(
        bbox: Annotated[
            list[float],
            Field(
                min_length=4,
                max_length=4,
                description="minx,miny,maxx,maxy in longitude and latitude",
            ),
        ],
        width: Annotated[int, Field(ge=1, le=MAX_SIZE)] = DEFAULT_SIZE,
        height: Annotated[int, Field(ge=1, le=MAX_SIZE)] = DEFAULT_SIZE,
        style: str | None = None,
    ) -> Image:
        path = f"{base}/map" if style is None else f"{base}/styles/{style}/map"
        params = {"bbox": ",".join(str(value) for value in bbox), "width": width, "height": height}
        response = await client.get(path, params={**params, "f": "png"})
        if response.status_code != 200 or not response.headers.get("content-type", "").startswith(
            "image/png"
        ):
            raise ToolError(_message(response))
        return Image(data=response.content, format="png")

    return Tool.from_function(
        get_map,
        name=fastmcp_name(f"get{collection.collection_id.capitalize()}Map"),
        title=f"Map of {collection.title}",
        description=f"A PNG map of a bbox of {collection.title}.{style_help}",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )


def add_map_tools(server: FastMCP, openapi_spec: dict, client: httpx2.AsyncClient) -> int:
    """Add a map tool to ``server`` for each map collection of the document."""
    collections = map_collections(openapi_spec)
    for collection in collections:
        server.add_tool(_map_tool(collection, client))
    return len(collections)
