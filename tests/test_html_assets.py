"""The compiled assets of the pages: the manifest's URLs and their cache.

``app.*`` is imported at the top of this module.
"""

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.html.assets import IMMUTABLE, STYLE, Assets, ImmutableFiles
from tests.html_fixtures import fake_build

SERVER = "http://example.org/geoapi"
FILES = f"{SERVER}/_html/assets"


def test_the_stylesheet_entry_is_its_own_file(tmp_path):
    assets = Assets(fake_build(tmp_path), f"{SERVER}/")

    assert assets.styles((STYLE,)) == [f"{FILES}/style-4f2a.css"]


def test_an_island_brings_its_stylesheets_once_and_in_order(tmp_path):
    assets = Assets(fake_build(tmp_path), SERVER)

    assert assets.styles((STYLE, "pages/api-docs.ts", "pages/api-docs.ts")) == [
        f"{FILES}/style-4f2a.css",
        f"{FILES}/api-docs-77aa.css",
    ]


def test_only_the_islands_have_scripts(tmp_path):
    assets = Assets(fake_build(tmp_path), SERVER)

    assert assets.scripts((STYLE, "pages/api-docs.ts")) == [f"{FILES}/api-docs-77aa.js"]


def test_an_entry_the_manifest_lacks_gives_nothing(tmp_path):
    assets = Assets(fake_build(tmp_path), SERVER)

    assert (assets.styles(("pages/nope.ts",)), assets.scripts(("pages/nope.ts",))) == ([], [])


def test_without_a_build_there_is_nothing_to_link(tmp_path):
    assets = Assets(tmp_path, SERVER)

    assert (assets.styles((STYLE,)), assets.scripts(("pages/api-docs.ts",))) == ([], [])


def test_a_compiled_file_is_cached_for_good_and_a_missing_one_is_not(tmp_path):
    app = Starlette(routes=[Mount("/_html", app=ImmutableFiles(directory=fake_build(tmp_path)))])
    client = TestClient(app)

    found = client.get("/_html/assets/style-4f2a.css")
    missing = client.get("/_html/assets/nope.css")

    assert (found.status_code, found.headers["cache-control"]) == (200, IMMUTABLE)
    assert (missing.status_code, "cache-control" in missing.headers) == (404, False)
