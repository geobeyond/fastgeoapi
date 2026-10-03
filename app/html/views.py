"""What each page shows: the variables of its template, from the route's JSON."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

from pygeoapi import l10n
from pygeoapi.formats import F_HTML, F_JSONLD
from pygeoapi.linked_data import jsonldify

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
