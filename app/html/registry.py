"""The pages fastgeoapi renders, by the path of their route."""

from app.html import collection, views
from app.html.pages import Page

PAGES: dict[str, Page] = {
    "/": Page("landing.html", views.landing),
    "/conformance": Page("conformance.html", views.conformance),
    "/TileMatrixSets": Page("tilematrixsets.html", views.tilematrixsets),
    "/TileMatrixSets/{tileMatrixSetId}": Page("tilematrixset.html", views.tilematrixset),
    "/collections": Page("collections.html", views.collections),
    "/collections/{collection_id:path}/queryables": Page("queryables.html", views.queryables),
    "/collections/{collection_id:path}/schema": Page("schema.html", views.schema),
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
