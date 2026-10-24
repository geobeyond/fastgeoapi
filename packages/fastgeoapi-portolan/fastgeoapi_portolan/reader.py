"""Reading a Portolan catalog the way the commands do.

obstore fetches the documents, from disk, http(s) or a bucket, and the
bundled schemas check them. The result types are those of the core,
re-exported here.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from typing import Any

from fastgeoapi_portolan.catalog.drivers import read_catalog_async, read_items_async
from fastgeoapi_portolan.catalog.protocols import MAX_DOCUMENT_BYTES
from fastgeoapi_portolan.catalog.results import (
    Catalog,
    Collection,
    Finding,
    Items,
    Nonconforming,
    Skipped,
    Validation,
)
from fastgeoapi_portolan.catalog.walk import MAX_DOCUMENTS
from fastgeoapi_portolan.storage import ObstoreTransport
from fastgeoapi_portolan.validation import JsonSchemaValidator

__all__ = [
    "Catalog",
    "Collection",
    "Finding",
    "Items",
    "Nonconforming",
    "Skipped",
    "Validation",
    "read_catalog",
    "read_items",
]


@cache
def _validator() -> JsonSchemaValidator:
    # Loading the schemas is the slow part; one validator serves every read.
    return JsonSchemaValidator()


async def read_catalog(
    location: str,
    store_options: Mapping[str, Any] | None = None,
    *,
    only: frozenset[str] | None = None,
    concurrency: int = 16,
    max_documents: int = MAX_DOCUMENTS,
    max_bytes: int = MAX_DOCUMENT_BYTES,
) -> Catalog:
    """Read the catalog at ``location`` and check every catalog and collection in it.

    ``store_options`` are those of a fastgeoapi configuration, for a
    catalog in a bucket. ``only`` keeps the collections with those ids.
    The walk reads at most ``max_documents``, each of at most ``max_bytes``.
    """
    return await read_catalog_async(
        location,
        ObstoreTransport(store_options, max_bytes=max_bytes),
        only=only,
        validator=_validator(),
        concurrency=concurrency,
        max_documents=max_documents,
    )


async def read_items(
    collection: Collection,
    store_options: Mapping[str, Any] | None = None,
    *,
    max_items: int = MAX_DOCUMENTS,
    max_bytes: int = MAX_DOCUMENT_BYTES,
) -> Items:
    """Read and check the items ``collection`` links, each of at most ``max_bytes``.

    A collection that links more than ``max_items`` raises ``ValueError``.
    """
    return await read_items_async(
        collection,
        ObstoreTransport(store_options, max_bytes=max_bytes),
        validator=_validator(),
        max_items=max_items,
    )
