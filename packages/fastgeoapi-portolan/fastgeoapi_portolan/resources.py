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
from fastgeoapi_portolan.geoparquet import geoparquet_provider
from fastgeoapi_portolan.handlers import Handler, IngestOptions, ProviderMatch, Refusal
from fastgeoapi_portolan.reader import (
    Catalog,
    Collection,
    Finding,
    NonconformingDocument,
    SkippedDocument,
)
from fastgeoapi_portolan.tiles import pmtiles_provider

# In the order their providers appear in a resource.
HANDLERS: tuple[tuple[str, Handler], ...] = (
    ("geoparquet", geoparquet_provider),
    ("pmtiles", pmtiles_provider),
)
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
_LINK_RELS = ("describedby", "via", "license")
_LINK_TITLES = {"describedby": "README", "via": "Source"}
# License values that are not an SPDX identifier.
_NOT_SPDX = frozenset({"other", "proprietary", "various"})
# pygeoapi reads ${NAME} in a configuration as a variable of the server's environment.
_VARIABLE = "${"


class DuplicateCollectionIdError(ValueError):
    """Two collections would become resources with one id."""


@dataclass(frozen=True)
class IngestedResource:
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


def _variable_at(value: Any, path: str) -> str | None:
    """Where a string or a key in ``value`` holds ``${``; ``store_options`` are left out.

    The store options are the user's, and a variable there can be meant.
    """
    if isinstance(value, str):
        return path if _VARIABLE in value else None
    if isinstance(value, Mapping):
        for key, item in value.items():
            where = f"{path}.{key}" if path else str(key)
            if _VARIABLE in str(key):
                return where
            found = None if key == "store_options" else _variable_at(item, where)
            if found is not None:
                return found
    if isinstance(value, list):
        for index, item in enumerate(value):
            found = _variable_at(item, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def _rejected(entry: NonconformingDocument) -> SkippedDocument:
    identifier = entry.document.get("id")
    name = identifier if isinstance(identifier, str) and identifier else entry.href
    return SkippedDocument(name, _not_conforming(entry.findings))


async def _resource(
    collection: Collection, catalog: Catalog, ingest_options: IngestOptions, prefix: str
) -> IngestedResource | SkippedDocument:
    document = collection.document
    title, description = _text(document, "title"), _text(document, "description")
    if title is None:
        return SkippedDocument(collection.id, "the collection has no title")
    if description is None:
        return SkippedDocument(collection.id, "the collection has no description")
    extents = _extents(document)
    if extents is None:
        return SkippedDocument(collection.id, "the collection has no spatial extent")

    providers: list[dict[str, Any]] = []
    choices: list[str] = []
    refusals: list[tuple[str, str]] = []
    for name, handler in HANDLERS:
        result = await handler(collection, ingest_options)
        if isinstance(result, ProviderMatch):
            providers.append(result.provider)
            choices.extend(result.choices)
        elif isinstance(result, Refusal) and result.transient:
            # Half a resource would replace the whole one already configured.
            reason = f"{name}: {result.reason}; nothing changes until it can be read"
            return SkippedDocument(collection.id, reason)
        elif isinstance(result, Refusal):
            refusals.append((name, result.reason))
    if not providers:
        reason = "; ".join(why for _, why in refusals) if refusals else _unhandled(document)
        return SkippedDocument(collection.id, reason)
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
    # The root is the one given on the command line; the rest comes from the catalog.
    from_catalog = {key: value for key, value in ingest.items() if key != "catalog"}
    where = _variable_at({"id": collection.id, **resource, "ingest": from_catalog}, "")
    if where is not None:
        reason = f"{where} holds '${{', which the configuration reads as a variable"
        return SkippedDocument(collection.id, reason)
    resource["ingest"] = ingest
    return IngestedResource(f"{prefix}{collection.id}", resource, tuple(choices))


async def build(
    catalog: Catalog, ingest_options: IngestOptions, *, prefix: str = ""
) -> tuple[list[IngestedResource], list[SkippedDocument]]:
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
    built: list[IngestedResource] = []
    for collection in catalog.collections:
        result = await _resource(collection, catalog, ingest_options, prefix)
        if isinstance(result, IngestedResource):
            built.append(result)
        else:
            skipped.append(result)
    return built, skipped
