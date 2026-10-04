"""The pages of coverages and of environmental data."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from app.html.collection import REL, collection_crumbs, preview
from app.html.maps import extent_of
from app.html.pages import PageContext, Related
from app.html.parameters import Field
from app.html.views import Gettext, base_url

THE_SCHEMA = Related("schema", "/collections/{collection_id:path}/schema")
"""The schema of the collection a page belongs to."""

COVERAGE_PARAMETERS = ("bbox", "datetime", "subset", "properties")
"""The parameters of the coverage route a download is narrowed with."""

COVERAGE_FORMATS = {
    "application/prs.coverage+json": "CoverageJSON",
    "application/tiff": "GeoTIFF",
}
"""How the page names the formats a coverage downloads in."""

BY = " \u00d7 "
"""What stands between the sizes of a grid's axes: the multiplication sign."""


def temporal_of(collection: dict[str, Any]) -> list | None:
    """The temporal intervals of a collection's JSON, None without a temporal extent."""
    return ((collection.get("extent") or {}).get("temporal") or {}).get("interval")


def datetime_field(params: dict[str, str], _: Gettext) -> Field:
    """The field of ``datetime``, as every form of the pages has it."""
    return Field(
        "datetime",
        _("Date and time"),
        "text",
        params.get("datetime", ""),
        hint=_("An instant, or an interval such as 2020-01-01/2020-12-31 or ../2020-12-31"),
    )


def coverage(context: PageContext) -> dict[str, Any]:
    """A coverage, from its collection and its schema, with its downloads.

    The coverage itself is not read: describing it would load every value.
    So the page cannot repeat the refusal of a collection without a
    coverage either; it shows that collection's facts without downloads.
    """
    _ = context.gettext
    collection_id = context.path_params["collection_id"]
    described = context.related["collection"]
    resource = context.api.config["resources"].get(collection_id, {})
    title = described.get("title") or collection_id
    action = f"{base_url(context)}/collections/{collection_id}/coverage"
    narrowed = [
        (name, value) for name, value in context.params.items() if name in COVERAGE_PARAMETERS
    ]
    downloads = []
    for link in described.get("links", []):
        if link.get("rel") != f"{REL}coverage" or link.get("type") in (None, "text/html"):
            continue
        format_ = parse_qs(urlsplit(link["href"]).query).get("f", [""])[0]
        downloads.append(
            {
                "label": COVERAGE_FORMATS.get(link["type"], link["type"]),
                "href": f"{action}?{urlencode([*narrowed, ('f', format_)])}",
            }
        )
    grid = ((described.get("extent") or {}).get("spatial") or {}).get("grid") or []
    bbox = extent_of(described)
    facts = [
        {"label": _("Grid"), "value": BY.join(str(axis.get("cellsCount")) for axis in grid)},
        {
            "label": _("Resolution"),
            "value": BY.join(
                f"{axis['resolution']:g}" for axis in grid if axis.get("resolution") is not None
            ),
        },
        {
            "label": _("Spatial extent"),
            "value": ", ".join(f"{value:g}" for value in bbox) if bbox else "",
        },
    ]
    fields = [
        Field(
            "bbox",
            _("Bounding box"),
            "bbox",
            context.params.get("bbox", ""),
            hint=_("West, south, east, north"),
        )
    ]
    if temporal_of(described):
        fields.append(datetime_field(context.params, _))
    fields += [
        Field(
            "subset",
            _("Subset"),
            "text",
            context.params.get("subset", ""),
            hint=_("Ranges of the axes, such as x(12.2:12.5),y(41.7:41.9)"),
        ),
        Field(
            "properties",
            _("Bands"),
            "text",
            context.params.get("properties", ""),
            hint=_("Names separated by commas"),
        ),
    ]
    schema = context.related.get("schema") or {}
    return {
        "title": _("Coverage of %(collection)s") % {"collection": title},
        "description": described.get("description", ""),
        "facts": [fact for fact in facts if fact["value"]],
        "bands": [
            {"name": name, "title": spec.get("title") or "", "type": spec.get("type", "")}
            for name, spec in (schema.get("properties") or {}).items()
        ],
        "action": action,
        "language": context.params.get("lang"),
        "fields": fields,
        "downloads": downloads,
        "map": preview(context, collection_id, resource),
        "crumbs": collection_crumbs(context, title, {"label": _("Coverage")}),
    }
