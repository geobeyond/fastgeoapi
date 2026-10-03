"""The pages fastgeoapi renders, by the path of their route."""

from app.html import views
from app.html.pages import Page

PAGES: dict[str, Page] = {
    "/": Page("landing.html", views.landing),
}
