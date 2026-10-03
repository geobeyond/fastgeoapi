"""What each page shows: the variables of its template, from the route's JSON."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from pygeoapi import l10n
from pygeoapi.formats import F_HTML, F_JSONLD
from pygeoapi.linked_data import jsonldify, jsonldify_collection

from app.html.pages import PageContext, with_query
from app.pygeoapi.registry import active_specs

Gettext = Callable[[str], str]

PROCESSES = "http://www.opengis.net/def/rel/ogc/1.0/processes"
TILING_SCHEMES = "http://www.opengis.net/def/rel/ogc/1.0/tiling-schemes"

DESCRIPTION_LENGTH = 180
"""How much of a description a card shows."""


@jsonldify
def _catalog(api: Any, request: Any) -> dict[str, Any]:
    # pygeoapi's decorator builds the catalog from the configuration and
    # leaves it on the API object; this function hands it back.
    return dict(api.fcmld)


def catalog_jsonld(api: Any, locale: Any) -> dict[str, Any]:
    """The service as a schema.org DataCatalog, as pygeoapi writes it for JSON-LD."""
    return _catalog(api, SimpleNamespace(format=F_JSONLD, locale=locale))


def provider_kinds(resource: dict[str, Any], _: Gettext) -> list[str]:
    """What a collection serves, one label per kind, from its providers."""
    labels = {
        "feature": _("Features"),
        "record": _("Records"),
        "map": _("Map"),
        "coverage": _("Coverage"),
        "edr": _("Environmental data"),
    }
    kinds: list[str] = []
    for provider in resource.get("providers") or []:
        kind = provider.get("type")
        label = _tile_kind(provider, _) if kind == "tile" else labels.get(kind)
        if label is not None and label not in kinds:
            kinds.append(label)
    return kinds


def _tile_kind(provider: dict[str, Any], _: Gettext) -> str:
    if (provider.get("options") or {}).get("dem"):
        return _("Elevation tiles")
    if (provider.get("format") or {}).get("mimetype", "").startswith("image/"):
        return _("Raster tiles")
    return _("Vector tiles")


def card(
    title: str, description: str, href: str, badges: list[str], keywords: list[str]
) -> dict[str, Any]:
    """One card of a grid of collections or processes, its description cut short."""
    if len(description) > DESCRIPTION_LENGTH:
        description = description[:DESCRIPTION_LENGTH].rsplit(" ", 1)[0] + "…"
    return {
        "title": title,
        "description": description,
        "href": href,
        "badges": badges,
        "keywords": keywords,
    }


def base_url(context: PageContext) -> str:
    """The service's URL, without a trailing slash."""
    return context.api.base_url.rstrip("/")


def html_link(links: list[dict[str, Any]]) -> str | None:
    """The HTML representation among a resource's own links."""
    return next(
        (
            link["href"]
            for link in links
            if link.get("type") == "text/html"
            and link.get("rel") in ("self", "alternate")
            and link.get("href")
        ),
        None,
    )


def landing(context: PageContext) -> dict[str, Any]:
    """The service, its sections and its collections."""
    _ = context.gettext
    api = context.api
    locale = context.request.locale
    sections = [("data", _("Collections")), (PROCESSES, _("Processes"))]
    if "tiles" in active_specs(api.config):
        sections.append((TILING_SCHEMES, _("Tile matrix sets")))
    sections += [("service-doc", _("API documentation")), ("conformance", _("Conformance"))]
    hrefs: dict[str, str] = {}
    for link in context.document.get("links", []):
        hrefs.setdefault(link.get("rel", ""), link.get("href", ""))
    base = base_url(context)
    return {
        "title": context.document.get("title", ""),
        "description": context.document.get("description", ""),
        "sections": [
            {"label": label, "href": with_query(hrefs[rel], f=F_HTML)}
            for rel, label in sections
            if hrefs.get(rel)
        ],
        "collections": [
            card(
                l10n.translate(resource.get("title"), locale) or name,
                l10n.translate(resource.get("description"), locale) or "",
                f"{base}/collections/{name}?f=html",
                provider_kinds(resource, _),
                [],
            )
            for name, resource in api.config.get("resources", {}).items()
            if resource.get("type") == "collection"
        ],
        "jsonld": catalog_jsonld(api, locale),
    }


def _standard(uri: str) -> str:
    """The standard a conformance class belongs to: ``ogcapi-features-1 1.0``."""
    _, found, path = uri.partition("/spec/")
    if not found:
        return uri
    name, _, rest = path.partition("/")
    return f"{name} {rest.partition('/')[0]}".strip()


def conformance(context: PageContext) -> dict[str, Any]:
    """The conformance classes, grouped by standard."""
    _ = context.gettext
    groups: dict[str, list[str]] = {}
    for uri in context.document.get("conformsTo", []):
        groups.setdefault(_standard(uri), []).append(uri)
    return {
        "title": _("Conformance"),
        "description": _("The conformance classes this service implements."),
        "groups": [
            {"standard": standard, "classes": sorted(classes)}
            for standard, classes in sorted(groups.items())
        ],
        "crumbs": [{"label": _("Conformance")}],
    }


def tilematrixsets(context: PageContext) -> dict[str, Any]:
    """The tile matrix sets, each linked to its page."""
    _ = context.gettext
    base = base_url(context)
    return {
        "title": _("Tile matrix sets"),
        "description": _("The tiling schemes the tiles of this service can be requested in."),
        "rows": [
            {
                "id": tms["id"],
                "title": tms.get("title") or tms["id"],
                "uri": tms.get("uri"),
                "href": html_link(tms.get("links", []))
                or f"{base}/TileMatrixSets/{tms['id']}?f=html",
            }
            for tms in context.document.get("tileMatrixSets", [])
        ],
        "crumbs": [{"label": _("Tile matrix sets")}],
    }


def tilematrixset(context: PageContext) -> dict[str, Any]:
    """One tile matrix set: its reference system and its levels."""
    _ = context.gettext
    document = context.document
    crs = document.get("crs")
    crs = crs.get("uri") if isinstance(crs, dict) else crs
    facts = [
        {"label": _("Identifier"), "value": document.get("id")},
        {"label": _("URI"), "value": document.get("uri"), "href": document.get("uri")},
        {"label": _("Coordinate reference system"), "value": crs, "href": crs},
        {"label": _("Axes"), "value": ", ".join(document.get("orderedAxes", []))},
        {
            "label": _("Well-known scale set"),
            "value": document.get("wellKnownScaleSet"),
            "href": document.get("wellKnownScaleSet"),
        },
    ]
    return {
        "title": document.get("title") or document.get("id", ""),
        "facts": [fact for fact in facts if fact["value"]],
        "matrices": document.get("tileMatrices", []),
        "crumbs": [
            {"label": _("Tile matrix sets"), "href": f"{base_url(context)}/TileMatrixSets?f=html"},
            {"label": document.get("id", "")},
        ],
    }


def collections(context: PageContext) -> dict[str, Any]:
    """The collections as cards, and as datasets of the catalog's JSON-LD."""
    _ = context.gettext
    api = context.api
    locale = context.request.locale
    resources = api.config.get("resources", {})
    listed = context.document.get("collections", [])
    catalog = catalog_jsonld(api, locale)
    catalog["dataset"] = [jsonldify_collection(api, item, locale) for item in listed]
    return {
        "title": _("Collections"),
        "description": _("The collections of this service."),
        "collections": [
            card(
                item.get("title") or item["id"],
                item.get("description") or "",
                html_link(item.get("links", []))
                or f"{base_url(context)}/collections/{item['id']}?f=html",
                provider_kinds(resources.get(item["id"], {}), _),
                list(item.get("keywords") or []),
            )
            for item in listed
        ],
        "jsonld": catalog,
        "crumbs": [{"label": _("Collections")}],
    }


def _properties(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "title": spec.get("title", ""),
            "type": spec.get("type") or spec.get("format") or spec.get("$ref") or "",
            "role": spec.get("x-ogc-role", ""),
            "description": spec.get("description", ""),
            "allowed": [str(value) for value in spec.get("enum", [])],
        }
        for name, spec in (document.get("properties") or {}).items()
    ]


def _collection_crumbs(context: PageContext, title: str, last: str) -> list[dict[str, str]]:
    _ = context.gettext
    base = base_url(context)
    collection = context.path_params.get("collection_id", "")
    return [
        {"label": _("Collections"), "href": f"{base}/collections?f=html"},
        {"label": title, "href": f"{base}/collections/{collection}?f=html"},
        {"label": last},
    ]


def queryables(context: PageContext) -> dict[str, Any]:
    """The properties a filter on the items of a collection can use."""
    _ = context.gettext
    title = context.document.get("title") or context.path_params.get("collection_id", "")
    return {
        "title": _("Queryables of %(collection)s") % {"collection": title},
        "description": _("The properties a filter on the items can use."),
        "properties": _properties(context.document),
        "crumbs": _collection_crumbs(context, title, _("Queryables")),
    }


def schema(context: PageContext) -> dict[str, Any]:
    """The properties of the items of a collection, as their schema describes them."""
    _ = context.gettext
    title = context.document.get("title") or context.path_params.get("collection_id", "")
    return {
        "title": _("Schema of %(collection)s") % {"collection": title},
        "description": _("The properties of the items, as their schema describes them."),
        "properties": _properties(context.document),
        "crumbs": _collection_crumbs(context, title, _("Schema")),
    }
