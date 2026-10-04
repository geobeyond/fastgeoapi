"""The pages fastgeoapi renders, by the path of their route."""

from dataclasses import replace

from app.html import collection, coverages, features, views
from app.html.pages import Page

PAGES: dict[str, Page] = {
    "/": Page("landing.html", views.landing),
    "/conformance": Page("conformance.html", views.conformance),
    "/TileMatrixSets": Page("tilematrixsets.html", views.tilematrixsets),
    "/TileMatrixSets/{tileMatrixSetId}": Page("tilematrixset.html", views.tilematrixset),
    "/collections": Page("collections.html", views.collections),
    "/collections/{collection_id:path}/queryables": Page("queryables.html", views.queryables),
    "/collections/{collection_id:path}/schema": Page("schema.html", views.schema),
    "/collections/{collection_id:path}/tiles": Page(
        "tilesets.html",
        collection.tilesets,
        islands=collection.MAP_ISLAND,
        related=(collection.THE_COLLECTION,),
    ),
    "/collections/{collection_id:path}/tiles/{tileMatrixSetId}": Page(
        "tileset.html",
        collection.tileset,
        islands=collection.MAP_ISLAND,
        related=(collection.THE_COLLECTION,),
    ),
    "/collections/{collection_id:path}/tiles/{tileMatrixSetId}/metadata": Page(
        "tileset.html",
        collection.tileset,
        islands=collection.MAP_ISLAND,
        related=(collection.THE_COLLECTION,),
    ),
    "/collections/{collection_id:path}/coverage": Page(
        "coverage.html",
        coverages.coverage,
        islands=collection.MAP_ISLAND,
        needs_document=False,
        related=(replace(collection.THE_COLLECTION, required=True), coverages.THE_SCHEMA),
    ),
    "/collections/{collection_id:path}/items/{item_id:path}": Page(
        "item.html",
        features.item,
        islands=collection.MAP_ISLAND,
        related=(collection.THE_COLLECTION,),
    ),
    "/collections/{collection_id:path}/items": Page(
        "items.html",
        features.items,
        islands=collection.MAP_ISLAND,
        related=(collection.THE_COLLECTION, features.THE_QUERYABLES),
        on_bad_request=True,
    ),
    "/collections/{collection_id:path}": Page(
        "collection.html", collection.collection, islands=collection.MAP_ISLAND
    ),
    "/openapi": Page(
        "openapi.html", views.openapi, islands=("pages/api-docs.ts",), needs_document=False
    ),
    "/processes": Page("processes.html", views.processes),
    "/processes/{process_id}": Page(
        "process.html", views.process, islands=("pages/process-run.ts",)
    ),
    "/jobs": Page("jobs.html", views.jobs),
    "/jobs/{job_id}": Page("job.html", views.job, islands=("pages/job-status.ts",)),
    "/jobs/{job_id}/results": Page("results.html", views.results),
}

EDR_QUERIES = ("position", "area", "cube", "radius", "trajectory", "corridor", "locations")
"""The EDR queries pygeoapi routes, each with and without an instance."""

_EDR_QUERY = Page(
    "edr.html",
    coverages.edr_query,
    islands=collection.MAP_ISLAND,
    related=(collection.THE_COLLECTION,),
    on_bad_request=True,
)

_INSTANCE = "/collections/{collection_id:path}/instances/{instance_id}"

PAGES.update(
    {
        "/collections/{collection_id:path}/instances": Page(
            "instances.html",
            coverages.instances,
            islands=collection.MAP_ISLAND,
            related=(collection.THE_COLLECTION,),
        ),
        _INSTANCE: Page(
            "instance.html",
            coverages.instance,
            islands=collection.MAP_ISLAND,
            related=(collection.THE_COLLECTION,),
        ),
        "/collections/{collection_id:path}/locations/{location_id}": _EDR_QUERY,
        f"{_INSTANCE}/locations/{{location_id}}": _EDR_QUERY,
        **{f"/collections/{{collection_id:path}}/{query}": _EDR_QUERY for query in EDR_QUERIES},
        **{f"{_INSTANCE}/{query}": _EDR_QUERY for query in EDR_QUERIES},
    }
)
