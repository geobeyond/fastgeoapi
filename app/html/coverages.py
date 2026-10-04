"""The pages of coverages and of environmental data."""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from app.html.collection import REL, collection_crumbs, edr_label, preview
from app.html.features import feature_name
from app.html.maps import basemap, camera, domain_footprint, extent_of, features_island
from app.html.pages import PageContext, Related
from app.html.parameters import Field, parameter_of
from app.html.views import Gettext, base_url, html_link, json_links, parameter_row

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


AXIS_VALUES = 5
"""How many values of an axis or of a range the tables show."""

QUERY_GEOMETRIES = {
    "position": "POINT(12.5 41.9)",
    "radius": "POINT(12.5 41.9)",
    "area": "POLYGON((12 41, 13 41, 13 42, 12 42, 12 41))",
    "trajectory": "LINESTRING(12 41, 13 42)",
    "corridor": "LINESTRING(12 41, 13 42)",
}
"""An example of the coordinates of each EDR query that takes them."""


def edr_where(context: PageContext) -> tuple[str, str | None]:
    """The collection and the instance of an EDR page.

    ``{collection_id:path}`` is greedy: an instance query reaches the plain
    query's route with ``name/instances/2026`` as the collection.
    """
    collection_id, found, instance = context.path_params["collection_id"].partition("/instances/")
    return collection_id, instance if found else context.path_params.get("instance_id")


def _query_type(context: PageContext) -> str:
    if "location_id" in context.path_params:
        return "locations"
    return urlsplit(context.url).path.rstrip("/").rsplit("/", 1)[-1]


def edr_fields(
    query_type: str, collection: dict[str, Any], params: dict[str, str], _: Gettext
) -> list[Field]:
    """The fields of an EDR query: its geometry, then height, time, parameters and CRS."""
    fields = []
    if query_type in QUERY_GEOMETRIES:
        fields.append(
            Field(
                "coords",
                _("Coordinates"),
                "text",
                params.get("coords", ""),
                hint=_("Well-known text, such as %(example)s")
                % {"example": QUERY_GEOMETRIES[query_type]},
            )
        )
    if query_type == "cube":
        fields.append(
            Field(
                "bbox",
                _("Bounding box"),
                "bbox",
                params.get("bbox", ""),
                hint=_("West, south, east, north"),
            )
        )
    if query_type == "radius":
        fields.append(Field("within", _("Radius"), "number", params.get("within", "")))
        fields.append(
            Field(
                "within-units",
                _("Units of the radius"),
                "select",
                params.get("within-units", ""),
                (("", ""), ("km", "km"), ("m", "m"), ("mi", "mi")),
            )
        )
    fields.append(Field("z", _("Height"), "text", params.get("z", "")))
    if temporal_of(collection):
        fields.append(datetime_field(params, _))
    names = tuple((name, name) for name in collection.get("parameter_names") or {})
    if names:
        fields.append(
            Field(
                "parameter-name",
                _("Parameters"),
                "select",
                params.get("parameter-name", ""),
                (("", ""), *names),
            )
        )
    systems = tuple((uri, uri) for uri in collection.get("crs") or [])
    if len(systems) > 1:
        fields.append(
            Field(
                "crs",
                _("Coordinate reference system"),
                "select",
                params.get("crs", ""),
                (("", ""), *systems),
            )
        )
    return fields


def _first(values: list[Any]) -> str:
    shown = ", ".join(str(value) for value in values[:AXIS_VALUES])
    return f"{shown}, …" if len(values) > AXIS_VALUES else shown


def coverage_tables(
    document: dict[str, Any], locale: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The axes and the parameters of a CoverageJSON answer, with the first values of each."""
    first = (document.get("coverages") or [document])[0]
    axes = []
    for name, axis in ((first.get("domain") or {}).get("axes") or {}).items():
        if "values" in axis:
            axes.append(
                {"name": name, "shown": _first(axis["values"]), "count": len(axis["values"])}
            )
        else:
            axes.append(
                {
                    "name": name,
                    "shown": f"{axis.get('start')} … {axis.get('stop')}",
                    "count": axis.get("num"),
                }
            )
    parameters = []
    for name, spec in (document.get("parameters") or first.get("parameters") or {}).items():
        values = ((first.get("ranges") or {}).get(name) or {}).get("values") or []
        parameters.append({**parameter_row(name, spec, locale), "shown": _first(values)})
    return axes, parameters


def instances(context: PageContext) -> dict[str, Any]:
    """The instances of an EDR collection, each linked to its page."""
    _ = context.gettext
    collection_id = edr_where(context)[0]
    resource = context.api.config["resources"].get(collection_id, {})
    described = context.related.get("collection") or {}
    title = described.get("title") or collection_id
    base = base_url(context)
    return {
        "title": _("Instances of %(collection)s") % {"collection": title},
        "description": described.get("description", ""),
        "keywords": list(described.get("keywords") or []),
        "rows": [
            {
                "id": each["id"],
                "href": html_link(each.get("links", []))
                or f"{base}/collections/{collection_id}/instances/{each['id']}?f=html",
            }
            for each in context.document.get("instances", [])
        ],
        "map": preview(context, collection_id, resource),
        "crumbs": collection_crumbs(context, title, {"label": _("Instances")}),
    }


def instance(context: PageContext) -> dict[str, Any]:
    """An instance of an EDR collection, and the queries it answers."""
    _ = context.gettext
    collection_id, found = edr_where(context)
    instance_id = context.document.get("id") or found or ""
    resource = context.api.config["resources"].get(collection_id, {})
    described = context.related.get("collection") or {}
    title = described.get("title") or collection_id
    base = base_url(context)
    url = f"{base}/collections/{collection_id}/instances/{instance_id}"
    return {
        "title": _("Instance %(instance)s of %(collection)s")
        % {"instance": instance_id, "collection": title},
        "description": described.get("description", ""),
        "keywords": list(described.get("keywords") or []),
        "sections": [
            {"label": edr_label(name, _), "href": f"{url}/{name}?f=html"}
            for name in context.document.get("data_queries") or {}
            if name not in ("items", "instances")
        ],
        "links": json_links(context.document, context.request.locale),
        "map": preview(context, collection_id, resource),
        "crumbs": collection_crumbs(
            context,
            title,
            {
                "label": _("Instances"),
                "href": f"{base}/collections/{collection_id}/instances?f=html",
            },
            {"label": instance_id},
        ),
    }


def edr_query(context: PageContext) -> dict[str, Any]:
    """An EDR query: its form, and what it answered, in tables and on the map.

    Opened without parameters, the page is the blank form, and the map
    shows the collection.
    """
    _ = context.gettext
    api = context.api
    collection_id, instance_id = edr_where(context)
    query_type = _query_type(context)
    resource = api.config["resources"].get(collection_id, {})
    described = context.related.get("collection") or {}
    title = described.get("title") or collection_id
    fields = edr_fields(query_type, described, context.params, _)
    error_field = (
        parameter_of(context.error, [field.name for field in fields]) if context.error else None
    )
    document = context.document if isinstance(context.document, dict) else {}
    background = basemap(api.config)
    axes, parameters, listed, shown = [], [], [], None
    if document.get("type") == "FeatureCollection":
        listed = [
            {"index": index, "name": feature_name(feature, None)}
            for index, feature in enumerate(document.get("features") or [])
        ]
        shown = features_island(camera(resource, fit_data=True), background, document)
    elif document.get("domain") or document.get("coverages"):
        axes, parameters = coverage_tables(document, context.request.locale)
        footprints = [
            found
            for each in document.get("coverages") or [document]
            if (found := domain_footprint(each.get("domain") or {})) is not None
        ]
        if footprints:
            shown = features_island(
                camera(resource, fit_data=True),
                background,
                {"type": "FeatureCollection", "features": footprints},
            )
    label = edr_label(query_type, _)
    base = base_url(context)
    tail = []
    if instance_id:
        heading = _("%(query)s, %(collection)s, instance %(instance)s") % {
            "query": label,
            "collection": title,
            "instance": instance_id,
        }
        tail = [
            {
                "label": _("Instances"),
                "href": f"{base}/collections/{collection_id}/instances?f=html",
            },
            {
                "label": instance_id,
                "href": f"{base}/collections/{collection_id}/instances/{instance_id}?f=html",
            },
        ]
    else:
        heading = _("%(query)s, %(collection)s") % {"query": label, "collection": title}
    return {
        "title": heading,
        "action": context.url.split("?", 1)[0],
        "language": context.params.get("lang"),
        "fields": fields,
        "error": context.error,
        "error_field": error_field,
        "axes": axes,
        "parameters": parameters,
        "features": listed,
        "map": shown or preview(context, collection_id, resource),
        "crumbs": collection_crumbs(context, title, *tail, {"label": label}),
    }
