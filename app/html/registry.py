"""The pages fastgeoapi renders, by the path of their route."""

from app.html import views
from app.html.pages import Page

PAGES: dict[str, Page] = {
    "/": Page("landing.html", views.landing),
    "/conformance": Page("conformance.html", views.conformance),
    "/TileMatrixSets": Page("tilematrixsets.html", views.tilematrixsets),
    "/TileMatrixSets/{tileMatrixSetId}": Page("tilematrixset.html", views.tilematrixset),
}
