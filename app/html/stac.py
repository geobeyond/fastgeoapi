"""The pages of the STAC catalog: the root, a catalog, an item."""

from __future__ import annotations

from typing import Any

from pygeoapi import l10n

from app.html.maps import basemap, camera, features_island, footprint
from app.html.pages import PageContext, with_query
from app.html.views import Gettext, base_url

LISTING_COLUMNS = ("description", "type", "created", "size")
"""What a listing may say of each entry, in the order pygeoapi's pages show it."""

COLLECTION_FIELDS = ("id", "description", "extent", "cube:dimensions", "cube:variables")
"""What the page of a STAC collection shows, as pygeoapi's does."""


def _linked(links: list[dict[str, Any]], rel: str) -> list[dict[str, Any]]:
    """The links of ``rel`` to a page, opened with ``f=html``, with what they say of it."""
    return [
        {
            "title": link.get("title") or link["href"].rstrip("/").rsplit("/", 1)[-1],
            "href": with_query(link["href"], f="html"),
            "description": link.get("description", ""),
            "type": link.get("entry:type", ""),
            "created": link.get("created", ""),
            "size": link.get("file:size"),
        }
        for link in links
        if link.get("rel") == rel and link.get("href") and link.get("type") in (None, "text/html")
    ]


def _listing(rows: list[dict[str, Any]], _: Gettext) -> dict[str, Any]:
    """Entries of a catalog, with the columns at least one of them fills."""
    labels = {
        "description": _("Description"),
        "type": _("Type"),
        "created": _("Last modified"),
        "size": _("Size"),
    }
    return {
        "rows": rows,
        "columns": [
            {"key": key, "label": labels[key]}
            for key in LISTING_COLUMNS
            if any(row[key] not in (None, "") for row in rows)
        ],
    }


def _crumbs(base: str, parts: list[str]) -> list[dict[str, str]]:
    if not parts:
        return [{"label": "STAC"}]
    crumbs = [{"label": "STAC", "href": f"{base}/stac?f=html"}]
    crumbs += [
        {"label": part, "href": f"{base}/stac/{'/'.join(parts[: index + 1])}?f=html"}
        for index, part in enumerate(parts[:-1])
    ]
    return [*crumbs, {"label": parts[-1]}]


def stac(context: PageContext) -> dict[str, Any]:
    """The root, a catalog or an item: its children, its items, its assets, its footprint."""
    _ = context.gettext
    api = context.api
    document = context.document
    parts = [part for part in context.path_params.get("path", "").split("/") if part]
    base = base_url(context)
    is_item = document.get("type") == "Feature"
    if not parts:
        title = _("SpatioTemporal Asset Catalog")
    elif is_item or len(parts) > 1:
        title = document.get("id") if is_item else parts[-1]
    else:
        resource = api.config["resources"].get(parts[0], {})
        title = l10n.translate(resource.get("title"), context.request.locale) or parts[0]
    found = footprint(document) if is_item else None
    if document.get("type") == "Collection":
        shown = {name: document[name] for name in COLLECTION_FIELDS if name in document}
    elif is_item:
        shown = {"id": document.get("id"), **(document.get("properties") or {})}
    else:
        shown = {}
    return {
        "title": title,
        "description": document.get("description", ""),
        "stac_version": document.get("stac_version", ""),
        "children": _listing(_linked(document.get("links", []), "child"), _),
        "entries": _listing(_linked(document.get("links", []), "item"), _),
        "properties": [{"name": name, "value": value} for name, value in shown.items()],
        "assets": [
            {
                "name": name,
                "href": asset.get("href", ""),
                "type": asset.get("type", ""),
                "created": asset.get("created", ""),
                "size": asset.get("file:size"),
            }
            for name, asset in (document.get("assets") or {}).items()
        ],
        "map": features_island(
            camera({}, fit_data=True),
            basemap(api.config),
            {"type": "FeatureCollection", "features": [found]},
        )
        if found
        else None,
        "crumbs": _crumbs(base, parts),
    }
