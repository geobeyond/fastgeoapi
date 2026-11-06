"""Pydantic models of the catalog documents, for callers that validate their shape.

They need the ``models`` extra and come from ``scripts/generate_types.py``,
like the TypedDicts of the core; this module names the ones to use. They
check the shape only: the schemas themselves decide whether a document
conforms.
"""

from fastgeoapi_portolan.models.catalog import StacCatalogSpecification as CatalogModel
from fastgeoapi_portolan.models.collection import StacCollectionSpecification as CollectionModel
from fastgeoapi_portolan.models.item import Core3 as ItemModel

__all__ = ["CatalogModel", "CollectionModel", "ItemModel"]
