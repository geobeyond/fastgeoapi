"""What a walk returns: collections, rejected and skipped documents, warnings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from fastgeoapi_portolan.catalog.types import CollectionDocument, ItemDocument


@dataclass(frozen=True)
class Finding:
    """One schema error: where it is in the document, what fails, and which schema says so."""

    pointer: str
    message: str
    schema: str


@dataclass(frozen=True)
class Validation:
    """The errors a validator found, and the declared schemas it could not check."""

    findings: tuple[Finding, ...]
    unverified: tuple[str, ...]


@dataclass(frozen=True)
class NonconformingDocument:
    """A document a validator rejected, kept as it was read."""

    href: str
    kind: Literal["Catalog", "Collection", "Item"]
    document: dict[str, Any]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class Collection:
    """A collection, where it was found, the items it links and the profile it is held to.

    ``profile`` is the Portolan schema the collection declares, or the
    root's when it declares none.
    """

    id: str
    href: str
    document: CollectionDocument
    item_hrefs: tuple[str, ...]
    profile: str | None


@dataclass(frozen=True)
class SkippedDocument:
    """A document left out, and why.

    ``collection`` is the id, or the href when there is no id to give.
    """

    collection: str
    reason: str


@dataclass(frozen=True)
class Catalog:
    """What a walk of the catalog found.

    ``validated`` is false when no validator ran: the collections are then
    typed but nothing about them was checked.
    """

    root: str
    portolan_schema: str | None
    collections: tuple[Collection, ...]
    nonconforming: tuple[NonconformingDocument, ...]
    skipped: tuple[SkippedDocument, ...]
    warnings: tuple[str, ...]
    validated: bool


@dataclass(frozen=True)
class Items:
    """The items of a collection, in the order it links them, and the ones rejected."""

    items: tuple[ItemDocument, ...]
    nonconforming: tuple[NonconformingDocument, ...]
