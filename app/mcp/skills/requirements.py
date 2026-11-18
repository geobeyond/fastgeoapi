"""The skills the MCP server can serve, and what each needs from the API."""

from __future__ import annotations

from pathlib import Path

from app.mcp.skills.selection import FileRequirement, Operation, SkillRequirement

SKILLS_DIRECTORY = Path(__file__).parent
"""The folder that holds one folder per skill."""

ITEMS = Operation(method="GET", path=r"/collections/[^/]+/items")

SKILL_REQUIREMENTS: tuple[SkillRequirement, ...] = (
    SkillRequirement(name="ogcapi-orientation", parameters=("f",)),
    SkillRequirement(
        name="ogcapi-features",
        needs=(ITEMS,),
        parameters=(
            "bbox",
            "bbox-crs",
            "datetime",
            "limit",
            "properties",
            "sortby",
            "skipGeometry",
        ),
        files={
            "cql2.md": FileRequirement(
                needs=(Operation(method="GET", path=ITEMS.path, parameter="filter"),),
                parameters=("filter", "filter-lang", "filter-crs"),
            )
        },
    ),
    SkillRequirement(
        name="ogcapi-processes",
        needs=(Operation(method="POST", path=r"/processes/[^/]+/execution"),),
        parameters=("Prefer",),
    ),
    SkillRequirement(
        name="ogcapi-maps",
        needs=(Operation(method="GET", path=r"/collections/[^/]+/map"),),
        parameters=("bbox", "width", "height"),
    ),
    SkillRequirement(
        name="ogcapi-tiles",
        needs=(Operation(method="GET", path=r"/collections/[^/]+/tiles"),),
    ),
)
"""The requirement of each skill, one per folder of ``SKILLS_DIRECTORY``."""
