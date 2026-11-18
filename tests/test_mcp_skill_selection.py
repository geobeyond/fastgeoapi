"""Which skills an OpenAPI document selects."""

from app.mcp.skills.selection import (
    FileRequirement,
    Operation,
    SkillRequirement,
    find_operations,
    select_skills,
)

ITEMS = Operation(method="GET", path=r"/collections/[^/]+/items")
MAP = Operation(method="GET", path=r"/collections/[^/]+/map")
FILTER = Operation(method="GET", path=r"/collections/[^/]+/items", parameter="filter")


def _spec(*operations: tuple[str, str, list[dict]]) -> dict:
    """An OpenAPI document with one operation per (method, path, parameters)."""
    paths: dict = {}
    for method, path, parameters in operations:
        paths.setdefault(path, {})[method] = {
            "operationId": f"{method}{len(paths)}",
            "parameters": parameters,
            "responses": {"200": {"description": "ok"}},
        }
    return {"openapi": "3.0.2", "info": {"title": "test", "version": "1"}, "paths": paths}


def test_a_skill_with_no_needs_is_always_selected():
    requirements = [SkillRequirement(name="orientation")]

    assert select_skills(_spec(), requirements) == {"orientation": frozenset()}


def test_a_skill_is_selected_when_one_of_its_operations_is_there():
    spec = _spec(("get", "/collections/lakes/items", []))
    requirements = [
        SkillRequirement(name="features", needs=(ITEMS,)),
        SkillRequirement(name="maps", needs=(MAP,)),
    ]

    assert select_skills(spec, requirements) == {"features": frozenset()}


def test_an_optional_file_is_kept_only_when_its_operation_is_there():
    requirements = [
        SkillRequirement(
            name="features", needs=(ITEMS,), files={"cql2.md": FileRequirement(needs=(FILTER,))}
        )
    ]
    without = _spec(("get", "/collections/lakes/items", [{"name": "bbox", "in": "query"}]))
    with_filter = _spec(("get", "/collections/lakes/items", [{"name": "filter", "in": "query"}]))

    assert select_skills(without, requirements) == {"features": frozenset()}
    assert select_skills(with_filter, requirements) == {"features": frozenset({"cql2.md"})}


def test_a_parameter_from_a_ref_is_named_after_its_file():
    spec = _spec(
        (
            "get",
            "/collections/lakes/items",
            [{"$ref": "#/components/parameters/sortby.yaml"}, {"name": "bbox", "in": "query"}],
        )
    )

    ((method, path, _, parameters),) = find_operations(spec)

    assert (method, path, parameters) == (
        "GET",
        "/collections/lakes/items",
        frozenset({"sortby", "bbox"}),
    )


def test_a_local_ref_is_named_after_the_parameter_it_points_to():
    spec = _spec(
        ("get", "/collections/rome/map", [{"$ref": "#/components/parameters/bbox-crs-epsg"}])
    )
    spec["components"] = {"parameters": {"bbox-crs-epsg": {"name": "bbox-crs", "in": "query"}}}

    ((_, _, _, parameters),) = find_operations(spec)

    assert parameters == frozenset({"bbox-crs"})
