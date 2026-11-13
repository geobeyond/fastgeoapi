"""What each tool generated from our OpenAPI document may do.

MCP clients read the tool annotations to decide how much to ask the user
before a call. In the spec ``destructiveHint`` defaults to true and,
like ``idempotentHint``, counts only when ``readOnlyHint`` is false, so a
tool with no annotations looks as dangerous as ``deleteJob``. The hints
follow from the HTTP method, with an exception for the ``POST`` that
pygeoapi describes for a CQL2 query on the items. Every
``FastMCP.from_openapi`` in the codebase uses them, like the route maps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.server.providers.openapi import OpenAPITool
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from fastmcp.utilities.openapi import HTTPRoute

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
"""Methods that only read."""


def annotations_for(method: str, path: str, operation_id: str) -> ToolAnnotations:
    """The annotations of the tool for one OpenAPI operation.

    Reads, and the CQL2 query that pygeoapi describes as a ``POST`` on
    the items, are read only. On an editable collection the same
    ``POST`` also adds a feature (operation ``getCQL2OrAdd…``), which
    writes without destroying. ``PUT`` and ``DELETE`` replace or remove,
    and doing it twice has the effect of doing it once. All of these act
    only on this API, so ``openWorldHint`` is false.

    The tool that runs a process is marked only as not read only. A
    pygeoapi process may write data or call other services, and nothing
    in the document says which, so its other hints keep the spec
    defaults.
    """
    method = method.upper()
    closed = {"open_world_hint": False}
    if method in READ_METHODS:
        return ToolAnnotations(read_only_hint=True, **closed)
    if method == "POST" and path.endswith("/items"):
        if operation_id.startswith("getCQL2OrAdd"):
            return ToolAnnotations(read_only_hint=False, destructive_hint=False, **closed)
        if operation_id.startswith("getCQL2"):
            return ToolAnnotations(read_only_hint=True, **closed)
    if method in ("PUT", "DELETE"):
        return ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True, **closed
        )
    return ToolAnnotations(read_only_hint=False)


def annotate_component(route: HTTPRoute, component) -> None:
    """Give a generated tool its annotations and a readable title.

    FastMCP calls this for every component it builds from the document,
    and it annotates tools only. The title comes from the operation's
    ``summary``; without it FastMCP shows the tool name.
    """
    if not isinstance(component, OpenAPITool):
        return
    component.annotations = annotations_for(route.method, route.path, route.operation_id or "")
    if route.summary:
        component.title = route.summary
