"""The pages fastgeoapi renders, by the path of their route."""

from app.html import views
from app.html.pages import Page

PAGES: dict[str, Page] = {
    "/": Page("landing.html", views.landing),
    "/conformance": Page("conformance.html", views.conformance),
    "/TileMatrixSets": Page("tilematrixsets.html", views.tilematrixsets),
    "/TileMatrixSets/{tileMatrixSetId}": Page("tilematrixset.html", views.tilematrixset),
    "/collections": Page("collections.html", views.collections),
    "/collections/{collection_id:path}/queryables": Page("queryables.html", views.queryables),
    "/collections/{collection_id:path}/schema": Page("schema.html", views.schema),
    "/openapi": Page(
        "openapi.html", views.openapi, islands=("pages/api-docs.ts",), needs_document=False
    ),
    "/processes": Page("processes.html", views.processes),
    "/processes/{process_id}": Page(
        "process.html", views.process, islands=("pages/process-run.ts",)
    ),
}
