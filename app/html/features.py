"""The items of a collection, and each item."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any
from urllib.parse import quote

from pygeoapi.linked_data import geojson2jsonld

from app.html.collection import collection_crumbs, provider_of
from app.html.maps import basemap, camera, drawn_features, features_island
from app.html.pages import PageContext, Related
from app.html.parameters import chips, honoured, items_fields, parameter_of
from app.html.views import as_text, base_url, json_links

THE_QUERYABLES = Related("queryables", "/collections/{collection_id:path}/queryables")
"""The queryables of the collection a page belongs to."""


def data_provider(resource: dict[str, Any]) -> dict[str, Any]:
    """The provider of the collection's items: features, else records; empty when it has none."""
    return provider_of(resource, "feature") or provider_of(resource, "record") or {}


def feature_name(feature: dict[str, Any], title_field: str | None) -> str:
    """What a feature is called: its title field, else its identifier."""
    value = (feature.get("properties") or {}).get(title_field) if title_field else None
    return str(value) if value not in (None, "") else str(feature.get("id", ""))


def item_url(base: str, collection_id: str, item_id: Any) -> str:
    """The URL of an item, its identifier quoted."""
    return f"{base}/collections/{collection_id}/items/{quote(str(item_id), safe='')}"


def _columns(features: list[dict[str, Any]], left_out: set[str]) -> list[str]:
    """Every property of the page, in the order the features bring them."""
    found: dict[str, None] = {}
    for feature in features:
        found.update(dict.fromkeys(feature.get("properties") or {}))
    return [name for name in found if name not in left_out]


def items(context: PageContext) -> dict[str, Any]:
    """The items of a collection: the form of their parameters, the chips, the list, the map.

    After a 400 the document is None: the page shows the form with the
    message, by its field when the page has that field, above the form
    otherwise.
    """
    _ = context.gettext
    api = context.api
    collection_id = context.path_params["collection_id"]
    resource = api.config["resources"].get(collection_id, {})
    described = context.related.get("collection") or {}
    queryables = context.related.get("queryables")
    title = described.get("title") or collection_id
    provider_def = data_provider(resource)
    applied = honoured(provider_def) if provider_def else None
    in_view, advanced = items_fields(
        queryables=queryables or {},
        collection=described,
        params=context.params,
        applied=applied,
        gettext=_,
    )
    shown = [field.name for field in (*in_view, *advanced)]
    error_field = parameter_of(context.error, shown) if context.error else None
    document = context.document or {}
    features = document.get("features") or []
    title_field = provider_def.get("title_field")
    uri_field = provider_def.get("uri_field")
    columns = _columns(
        features, {provider_def.get("id_field"), title_field, uri_field, "extent"} - {None}
    )
    base = base_url(context)
    listed = [
        {
            "index": index,
            "name": feature_name(feature, title_field),
            "href": f"{item_url(base, collection_id, feature.get('id'))}?f=html",
            "uri": (feature.get("properties") or {}).get(uri_field) if uri_field else None,
            "cells": [as_text((feature.get("properties") or {}).get(name)) for name in columns],
        }
        for index, feature in enumerate(features)
    ]
    count = None
    if context.document is not None and not features:
        count = _("No items")
    elif context.document is not None:
        returned = document.get("numberReturned", len(features))
        matched = document.get("numberMatched")
        count = (
            _("%(returned)s of %(matched)s items") % {"returned": returned, "matched": matched}
            if matched is not None
            else _("%(returned)s items") % {"returned": returned}
        )
    return {
        "title": _("Items of %(collection)s") % {"collection": title},
        "description": described.get("description", ""),
        "action": f"{base}/collections/{collection_id}/items",
        "language": context.params.get("lang"),
        "fields": in_view,
        "advanced": advanced,
        "advanced_open": error_field in {field.name for field in advanced}
        or any(field.value for field in advanced),
        "error": context.error,
        "error_field": error_field,
        "chips": chips(
            context.params,
            context.url,
            applied,
            None if queryables is None else (queryables.get("properties") or {}),
        ),
        "count": count,
        "features": listed,
        "name_column": title_field or "id",
        "uri_column": uri_field,
        "columns": columns,
        "map": features_island(
            camera(resource, fit_data=True),
            basemap(api.config),
            drawn_features(
                context.url,
                context.params.get("crs"),
                {"type": "FeatureCollection", "features": features},
            ),
        ),
        "jsonld": {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": title,
            "url": context.url,
            "numberOfItems": len(listed),
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": position,
                    "url": each["href"],
                    "name": each["name"],
                }
                for position, each in enumerate(listed, start=1)
            ],
        },
        "crumbs": collection_crumbs(context, title, {"label": _("Items")}),
    }


def item(context: PageContext) -> dict[str, Any]:
    """An item: its properties, its map, and pygeoapi's JSON-LD of it."""
    _ = context.gettext
    api = context.api
    document = context.document
    collection_id = context.path_params["collection_id"]
    resource = api.config["resources"].get(collection_id, {})
    title = (context.related.get("collection") or {}).get("title") or collection_id
    provider_def = data_provider(resource)
    name = feature_name(document, provider_def.get("title_field"))
    base = base_url(context)
    url = item_url(base, collection_id, document.get("id", context.path_params["item_id"]))
    id_field = provider_def.get("id_field")
    rows = [{"name": "id", "value": document.get("id")}] + [
        {"name": key, "value": value}
        for key, value in (document.get("properties") or {}).items()
        if key != id_field
    ]
    shown = None
    if document.get("geometry"):
        shown = features_island(
            camera(resource, fit_data=True),
            basemap(api.config),
            drawn_features(
                context.url,
                context.params.get("crs"),
                {"type": "FeatureCollection", "features": [document]},
            ),
        )
    # pygeoapi's function takes the properties out of the feature it is given.
    linked = geojson2jsonld(
        api,
        {"links": [], **deepcopy(document)},
        collection_id,
        identifier=url,
        id_field=provider_def.get("id_field", "id"),
    )
    return {
        "title": name,
        "rows": rows,
        "map": shown,
        "jsonld": json.loads(linked),
        "links": json_links(document, context.request.locale),
        "crumbs": collection_crumbs(
            context,
            title,
            {"label": _("Items"), "href": f"{base}/collections/{collection_id}/items?f=html"},
            {"label": name},
        ),
    }
