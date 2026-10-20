"""The documents of a catalog, typed from the STAC and extension schemas.

Each module under ``_generated`` follows one schema; this one combines them
into the shapes the reader returns. Inside a document, the values of
``assets`` and ``links`` keep the STAC types: read their extension fields
through ``Asset`` and ``Link``.
"""

from __future__ import annotations

from typing import TypedDict

from fastgeoapi_portolan.catalog._generated import (
    alternate_assets,
    catalog,
    collection,
    file,
    item,
    partition,
    table,
)

# web-map-links defines its one link field under a condition the generator
# cannot follow, so it is typed here.
_PMTilesLink = TypedDict("_PMTilesLink", {"pmtiles:layers": list[str]}, total=False)


class Link(collection.Link, _PMTilesLink):
    """A STAC link, with ``pmtiles:layers`` from web-map-links."""


class Asset(collection.Asset, file.Fields, alternate_assets.Assets, table.Fields):
    """A STAC asset, with the fields of file, alternate-assets and table."""


class CatalogDocument(catalog.StacCatalogSpecification):
    """A STAC catalog."""


class CollectionDocument(collection.StacCollectionSpecification, table.Fields, partition.Fields):
    """A STAC collection, with the fields of table and partition."""


class ItemDocument(item.Core3, table.Fields):
    """A STAC item, with the fields of table."""
