"""From the collections of a Portolan catalog to pygeoapi resources.

Each handler looks at every collection, and each one that recognises its
assets adds a provider. A collection that does not conform, lacks what a
pygeoapi resource needs, or that no handler serves is skipped with the
reason.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastgeoapi_portolan.catalog.locations import resolve
from fastgeoapi_portolan.geoparquet import geoparquet
from fastgeoapi_portolan.handlers import Handler, Overrides, Provided, Refused
from fastgeoapi_portolan.reader import Catalog, Collection, Finding, Nonconforming, Skipped
from fastgeoapi_portolan.tiles import pmtiles

# In the order their providers appear in a resource.
HANDLERS: tuple[tuple[str, Handler], ...] = (("geoparquet", geoparquet), ("pmtiles", pmtiles))
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
_LINK_RELS = ("describedby", "via", "license")
_LINK_TITLES = {"describedby": "README", "via": "Source"}
# License values that are not an SPDX identifier.
_NOT_SPDX = frozenset({"other", "proprietary", "various"})


class DuplicateCollectionIdError(ValueError):
    """Two collections would become resources with one id."""


@dataclass(frozen=True)
class Built:
    """A resource for the configuration, and where its values came from."""

    id: str
    resource: dict[str, Any]
    choices: tuple[str, ...]


def _text(document: Mapping[str, Any], key: str) -> str | None:
    value = document.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _links(collection: Collection) -> list[dict[str, str]]:
    """The README, source and license links, made absolute.

    Without a license link, the SPDX id of ``license`` gives one.
    """
    document = collection.document
    links = document.get("links")
    found = []
    for link in links if isinstance(links, list) else ():
        if not isinstance(link, Mapping) or link.get("rel") not in _LINK_RELS:
            continue
        href = link.get("href")
        if not isinstance(href, str) or not href:
            continue
        rel = str(link["rel"])
        found.append(
            {
                "type": str(link.get("type") or "text/html"),
                "rel": rel,
                "title": str(link.get("title") or _LINK_TITLES.get(rel, rel)),
                "href": resolve(collection.href, href),
            }
        )
    license_id = _text(document, "license")
    if (
        license_id
        and license_id not in _NOT_SPDX
        and all(link["rel"] != "license" for link in found)
    ):
        found.append(
            {
                "type": "text/html",
                "rel": "license",
                "title": license_id,
                "href": f"https://spdx.org/licenses/{license_id}.html",
            }
        )
    return found


def _extents(document: Mapping[str, Any]) -> dict[str, Any] | None:
    """The spatial extent in CRS84 and the temporal one, or ``None`` without a bbox."""
    extent = document.get("extent")
    if not isinstance(extent, Mapping):
        return None
    spatial = extent.get("spatial")
    boxes = spatial.get("bbox") if isinstance(spatial, Mapping) else None
    # STAC lists the overall bbox first.
    box = boxes[0] if isinstance(boxes, list) and boxes and isinstance(boxes[0], list) else None
    if not box:
        return None
    extents: dict[str, Any] = {"spatial": {"bbox": box, "crs": CRS84}}
    temporal = extent.get("temporal")
    intervals = temporal.get("interval") if isinstance(temporal, Mapping) else None
    if isinstance(intervals, list) and intervals and isinstance(intervals[0], list):
        span = dict(zip(("begin", "end"), intervals[0], strict=False))
        span = {key: value for key, value in span.items() if value is not None}
        if span:
            extents["temporal"] = span
    return extents


def _unhandled(document: Mapping[str, Any]) -> str:
    assets = document.get("assets")
    types = sorted(
        {
            str(asset.get("type"))
            for asset in (assets.values() if isinstance(assets, Mapping) else ())
            if isinstance(asset, Mapping)
            and asset.get("type")
            and {"data", "visual"} & set(asset.get("roles") or [])
        }
    )
    return f"format not handled yet: {', '.join(types) if types else 'no data or visual asset'}"


def _not_conforming(findings: tuple[Finding, ...]) -> str:
    if not findings:
        return "does not conform"
    first = findings[0]
    where = " ".join(part for part in (first.pointer, first.message) if part)
    more = f" (+{len(findings) - 1} more)" if len(findings) > 1 else ""
    return f"does not conform to {first.schema}: {where}{more}"


def _rejected(entry: Nonconforming) -> Skipped:
    identifier = entry.document.get("id")
    name = identifier if isinstance(identifier, str) and identifier else entry.href
    return Skipped(name, _not_conforming(entry.findings))


async def _resource(
    collection: Collection, catalog: Catalog, overrides: Overrides, prefix: str
) -> Built | Skipped:
    document = collection.document
    title, description = _text(document, "title"), _text(document, "description")
    if title is None:
        return Skipped(collection.id, "the collection has no title")
    if description is None:
        return Skipped(collection.id, "the collection has no description")
    extents = _extents(document)
    if extents is None:
        return Skipped(collection.id, "the collection has no spatial extent")

    providers: list[dict[str, Any]] = []
    choices: list[str] = []
    refusals: list[tuple[str, str]] = []
    for name, handler in HANDLERS:
        result = await handler(collection, overrides)
        if isinstance(result, Provided):
            providers.append(result.provider)
            choices.extend(result.choices)
        elif isinstance(result, Refused):
            refusals.append((name, result.reason))
    if not providers:
        reason = "; ".join(why for _, why in refusals) if refusals else _unhandled(document)
        return Skipped(collection.id, reason)
    choices.extend(f"{name} left out: {why}" for name, why in refusals)

    keywords = document.get("keywords")
    resource: dict[str, Any] = {
        "type": "collection",
        "title": title,
        "description": description,
        "keywords": [word for word in keywords if isinstance(word, str)]
        if isinstance(keywords, list)
        else [],
    }
    links = _links(collection)
    if links:
        resource["links"] = links
    resource["extents"] = extents
    resource["providers"] = providers
    ingest = {"from": "portolan", "catalog": catalog.root, "collection": collection.id}
    if catalog.portolan_schema:
        ingest["schema"] = catalog.portolan_schema
    resource["ingest"] = ingest
    return Built(f"{prefix}{collection.id}", resource, tuple(choices))


async def build(
    catalog: Catalog, overrides: Overrides, *, prefix: str = ""
) -> tuple[list[Built], list[Skipped]]:
    """The resources for the collections of ``catalog``, and the ones left out.

    ``prefix`` goes before every resource id. Two collections that would
    share an id raise ``DuplicateCollectionIdError`` before any handler runs.
    """
    owners: dict[str, str] = {}
    for collection in catalog.collections:
        identifier = f"{prefix}{collection.id}"
        if identifier in owners:
            raise DuplicateCollectionIdError(
                f"{owners[identifier]} and {collection.href} would both be the resource "
                f"{identifier}: pass --prefix, or pick one with --collection"
            )
        owners[identifier] = collection.href

    skipped = list(catalog.skipped)
    skipped += [_rejected(entry) for entry in catalog.nonconforming if entry.kind == "Collection"]
    built: list[Built] = []
    for collection in catalog.collections:
        result = await _resource(collection, catalog, overrides, prefix)
        if isinstance(result, Built):
            built.append(result)
        else:
            skipped.append(result)
    return built, skipped
