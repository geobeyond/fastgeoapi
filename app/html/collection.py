"""The page of a collection, and what its map previews."""

from __future__ import annotations

from typing import Any

from pygeoapi import l10n
from pygeoapi import plugin as pygeoapi_plugin
from pygeoapi.linked_data import jsonldify_collection

from app.config.logging import create_logger
from app.html.maps import (
    DEFAULT_MAX_SIZE,
    basemap,
    camera,
    extent_island,
    extent_of,
    features_island,
    image_island,
    tiles_island,
)
from app.html.pages import PageContext, Related, format_instant, with_query
from app.html.views import Gettext, base_url, catalog_jsonld, html_link, provider_kinds
from app.provider.tile_styles import tile_styles
from app.tiles.contract import TileContent

logger = create_logger("app.html.collection")

MAP_ISLAND = ("pages/map.ts",)
"""The island of every page with a map."""

WEB_MERCATOR = "WebMercatorQuad"
"""The tile matrix set a MapLibre map draws."""

REL = "http://www.opengis.net/def/rel/ogc/1.0/"


def provider_of(resource: dict[str, Any], kind: str) -> dict[str, Any] | None:
    """The collection's first provider of ``kind``."""
    return next(
        (each for each in resource.get("providers") or [] if each.get("type") == kind), None
    )


def tile_content(provider_def: dict[str, Any]) -> TileContent | None:
    """What the tile source of ``provider_def`` holds; None when it has no source or cannot say.

    A source that cannot be read (an archive out of reach, a file that is
    not an archive) must not take the page down: the preview moves on.
    The provider comes from ``pygeoapi.plugin``, where fastgeoapi's cached
    ``load_plugin`` replaces pygeoapi's.
    """
    try:
        provider = pygeoapi_plugin.load_plugin("provider", provider_def)
        source = getattr(provider, "source", None)
        return None if source is None else source.content()
    except Exception as error:
        logger.warning(
            f"the tiles of {provider_def.get('data')} cannot be described: {type(error).__name__}"
        )
        return None


def _tiles_preview(
    context: PageContext, collection_id: str, resource: dict[str, Any]
) -> dict[str, Any] | None:
    provider_def = provider_of(resource, "tile")
    if provider_def is None:
        return None
    schemes = (provider_def.get("options") or {}).get("schemes") or [WEB_MERCATOR]
    if WEB_MERCATOR not in schemes:
        return None
    content = tile_content(provider_def)
    if content is None:
        return None
    _ = context.gettext
    tilejson = (
        f"{base_url(context)}/collections/{collection_id}/tiles/{WEB_MERCATOR}/metadata?f=tilejson"
    )
    return tiles_island(
        camera(resource, tilejson_center=content.center),
        tile_styles(resource, tilejson, content),
        _("Default"),
        _("Style"),
    )


def map_images(
    context: PageContext, collection_id: str, provider_def: dict[str, Any]
) -> tuple[list[dict[str, str]], int]:
    """The maps a map provider draws, its default style first, and the widest image it allows."""
    _ = context.gettext
    options = provider_def.get("options") or {}
    url = f"{base_url(context)}/collections/{collection_id}"
    maps = [{"name": _("Default"), "url": f"{url}/map"}]
    maps += [
        {"name": name, "url": f"{url}/styles/{name}/map"}
        for name in options.get("styles") or {}
        if name != options.get("default_style")
    ]
    return maps, int(options.get("max_size") or DEFAULT_MAX_SIZE)


def preview(
    context: PageContext, collection_id: str, resource: dict[str, Any]
) -> dict[str, Any] | None:
    """The collection's map: its tiles, else map images, else its first items, else its extent."""
    _ = context.gettext
    found = _tiles_preview(context, collection_id, resource)
    if found is not None:
        return found
    background = basemap(context.api.config)
    map_def = provider_of(resource, "map")
    if map_def is not None:
        maps, max_size = map_images(context, collection_id, map_def)
        return image_island(
            camera(resource, map_image=True), background, maps, max_size, _("Style")
        )
    if provider_of(resource, "feature") or provider_of(resource, "record"):
        items = f"{base_url(context)}/collections/{collection_id}/items?f=json"
        return features_island(camera(resource), background, items)
    bbox = extent_of(resource)
    return None if bbox is None else extent_island(camera(resource), background, bbox)


def edr_label(name: str, _: Gettext) -> str:
    """What the page calls an EDR query."""
    labels = {
        "instances": _("Instances"),
        "position": _("Query at a position"),
        "area": _("Query in an area"),
        "cube": _("Query in a cube"),
        "radius": _("Query within a radius"),
        "trajectory": _("Query along a trajectory"),
        "corridor": _("Query in a corridor"),
        "locations": _("Locations"),
    }
    return labels.get(name, name)


def collection_crumbs(
    context: PageContext, title: str, *tail: dict[str, str]
) -> list[dict[str, str]]:
    """Collections, the collection, then ``tail``; the collection is a link if ``tail`` follows."""
    _ = context.gettext
    base = base_url(context)
    collection_id = context.path_params.get("collection_id", "").partition("/instances/")[0]
    own = {"label": title}
    if tail:
        own["href"] = f"{base}/collections/{collection_id}?f=html"
    return [{"label": _("Collections"), "href": f"{base}/collections?f=html"}, own, *tail]


def _sections(
    context: PageContext, collection_id: str, document: dict[str, Any]
) -> list[dict[str, str]]:
    _ = context.gettext
    url = f"{base_url(context)}/collections/{collection_id}"
    rels = {link.get("rel", "") for link in document.get("links", [])}
    offered = [
        ("items", f"{url}/items?f=html", _("Items")),
        (f"{REL}queryables", f"{url}/queryables?f=html", _("Queryables")),
        (f"{REL}schema", f"{url}/schema?f=html", _("Schema")),
        (f"{REL}coverage", f"{url}/coverage?f=html", _("Coverage")),
    ]
    sections = [{"label": label, "href": href} for rel, href, label in offered if rel in rels]
    if any(rel.startswith(f"{REL}tilesets-") for rel in rels):
        sections.append({"label": _("Tilesets"), "href": f"{url}/tiles?f=html"})
    sections += [
        {"label": edr_label(name, _), "href": f"{url}/{name}?f=html"}
        for name in document.get("data_queries") or {}
        if name != "items"
    ]
    return sections


def _facts(context: PageContext, document: dict[str, Any]) -> list[dict[str, Any]]:
    _ = context.gettext
    language = context.request.locale.language
    bbox = extent_of(document)
    temporal = (document.get("extent") or {}).get("temporal") or {}
    interval = (temporal.get("interval") or [[]])[0]
    start, end = ([*interval, None, None])[:2]
    when = (
        f"{format_instant(start, language) or '..'} / {format_instant(end, language) or '..'}"
        if start or end
        else None
    )
    facts = [
        {"label": _("Identifier"), "value": document.get("id")},
        {"label": _("Item type"), "value": document.get("itemType")},
        {
            "label": _("Spatial extent"),
            "value": ", ".join(f"{value:g}" for value in bbox) if bbox else None,
        },
        {"label": _("Temporal extent"), "value": when},
        {"label": _("Storage CRS"), "value": document.get("storageCrs")},
    ]
    return [fact for fact in facts if fact["value"]]


def collection(context: PageContext) -> dict[str, Any]:
    """A collection: what it offers, its facts, its links and the map that previews it."""
    _ = context.gettext
    api = context.api
    locale = context.request.locale
    document = context.document
    collection_id = document.get("id") or context.path_params["collection_id"]
    resource = api.config["resources"].get(collection_id, {})
    title = document.get("title") or collection_id
    # ``jsonldify_collection`` reads the catalog that ``catalog_jsonld`` leaves on the API.
    catalog_jsonld(api, locale)
    dataset = jsonldify_collection(api, document, locale)
    return {
        "title": title,
        "description": document.get("description", ""),
        "kinds": provider_kinds(resource, _),
        "keywords": list(document.get("keywords") or []),
        "sections": _sections(context, collection_id, document),
        "facts": _facts(context, document),
        "links": [
            {
                "title": l10n.translate(link.get("title"), locale) or link["href"],
                "href": link["href"],
            }
            for link in resource.get("links") or []
            if link.get("href")
        ],
        "map": preview(context, collection_id, resource),
        "jsonld": {"@context": "https://schema.org", **dataset},
        "crumbs": collection_crumbs(context, title),
    }


TILING_SCHEME = f"{REL}tiling-scheme"


def collection_only(params: dict[str, str]) -> dict[str, str]:
    """The path parameters of the collection, without the EDR instance its path may carry.

    ``{collection_id:path}`` is greedy: under an EDR instance it reads
    ``name/instances/2026``.
    """
    return {"collection_id": params["collection_id"].partition("/instances/")[0]}


THE_COLLECTION = Related("collection", "/collections/{collection_id:path}", adjust=collection_only)
"""The JSON of the collection a page belongs to."""


def _collection_title(context: PageContext, collection_id: str) -> str:
    return (context.related.get("collection") or {}).get("title") or collection_id


def tilesets(context: PageContext) -> dict[str, Any]:
    """The tilesets of a collection, one row each, and the map of its tiles."""
    _ = context.gettext
    collection_id = context.path_params["collection_id"]
    resource = context.api.config["resources"].get(collection_id, {})
    title = _collection_title(context, collection_id)
    base = base_url(context)
    rows = []
    for each in context.document.get("tilesets", []):
        tms = each.get("tileMatrixSetURI", "").rstrip("/").rsplit("/", 1)[-1]
        rows.append(
            {
                "title": each.get("title") or tms,
                "tms": tms,
                "data_type": each.get("dataType", ""),
                "href": html_link(each.get("links", []))
                or f"{base}/collections/{collection_id}/tiles/{tms}?f=html",
            }
        )
    return {
        "title": _("Tilesets of %(collection)s") % {"collection": title},
        "description": _("The tiles of this collection, one set for each tiling scheme."),
        "rows": rows,
        "map": preview(context, collection_id, resource),
        "crumbs": collection_crumbs(context, title, {"label": _("Tilesets")}),
    }


def tileset(context: PageContext) -> dict[str, Any]:
    """A tileset: its tiling scheme, the template of its tiles, its TileJSON, and its map."""
    _ = context.gettext
    document = context.document
    collection_id = context.path_params["collection_id"]
    tms = context.path_params["tileMatrixSetId"]
    resource = context.api.config["resources"].get(collection_id, {})
    title = _collection_title(context, collection_id)
    base = base_url(context)
    links = document.get("links", [])
    template = next((link["href"] for link in links if link.get("rel") == "item"), None)
    scheme = next((link["href"] for link in links if link.get("rel") == TILING_SCHEME), None)
    crs = document.get("crs")
    crs = crs.get("uri") if isinstance(crs, dict) else crs
    tilejson = f"{base}/collections/{collection_id}/tiles/{tms}/metadata?f=tilejson"
    facts = [
        {"label": _("Data type"), "value": document.get("dataType")},
        {"label": _("Coordinate reference system"), "value": crs, "href": crs},
        {
            "label": _("Tile matrix set"),
            "value": tms,
            "href": with_query(scheme, f="html") if scheme else None,
        },
        {"label": "TileJSON", "value": tilejson, "href": tilejson},
    ]
    return {
        "title": _("Tileset %(tileset)s of %(collection)s") % {"tileset": tms, "collection": title},
        "facts": [fact for fact in facts if fact["value"]],
        "template": template,
        "map": preview(context, collection_id, resource),
        "crumbs": collection_crumbs(
            context,
            title,
            {"label": _("Tilesets"), "href": f"{base}/collections/{collection_id}/tiles?f=html"},
            {"label": tms},
        ),
    }
