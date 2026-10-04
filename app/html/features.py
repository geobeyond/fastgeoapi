"""The items of a collection, and each item."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.html.collection import collection_crumbs, provider_of
from app.html.maps import basemap, camera, features_island
from app.html.pages import PageContext, Related
from app.html.parameters import chips, honoured, items_fields, parameter_of
from app.html.views import base_url

SUMMARY_PROPERTIES = 3
"""How many properties the list shows under the name of an item."""

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


def _summary(feature: dict[str, Any], title_field: str | None) -> str:
    shown = [
        f"{name}: {value}"
        for name, value in (feature.get("properties") or {}).items()
        if name != title_field and value not in (None, "") and not isinstance(value, dict | list)
    ]
    return " · ".join(shown[:SUMMARY_PROPERTIES])


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
    base = base_url(context)
    listed = [
        {
            "index": index,
            "name": feature_name(feature, title_field),
            "props": _summary(feature, title_field),
            "href": f"{item_url(base, collection_id, feature.get('id'))}?f=html",
        }
        for index, feature in enumerate(features)
    ]
    count = None
    if context.document is not None:
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
        "map": features_island(
            camera(resource, fit_data=True),
            basemap(api.config),
            {"type": "FeatureCollection", "features": features},
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
