"""The page of one collection: what it offers, its facts, and the map that previews it.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    CRS84,
    SERVER_URL,
    config,
    fake_build,
    island_config,
    jsonld,
    native_client,
    section,
    with_lost_tiles,
    with_map,
    with_tiles,
)

LICENSE = "https://creativecommons.org/licenses/by/4.0/"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("collection")
    api_config = with_lost_tiles(with_map(with_tiles(config(), directory), directory), directory)
    api_config["resources"]["obs"]["view"] = {"center": [-77.0, 44.0], "zoom": 5}
    lakes = api_config["resources"]["lakes"]
    lakes["links"].append(
        {"type": "text/html", "rel": "license", "title": "CC-BY 4.0", "href": LICENSE}
    )
    lakes["providers"][0]["storage_crs_coordinate_epoch"] = 2017.23
    return native_client(api_config, fake_build(directory / "static"))


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


def _preview(client, path):
    return island_config(_page(client, path).text, "fga-map")


def test_a_collection_of_features_previews_its_first_items(client):
    preview = _preview(client, "/collections/lakes")

    assert preview["kind"] == "features"
    assert preview["data"] == f"{SERVER_URL}/collections/lakes/items?f=json"
    assert preview["camera"]["bounds"] == [-180.0, -90.0, 180.0, 90.0]
    assert preview["basemap"]["url"] == "https://tile.openstreetmap.org/{z}/{x}/{y}.png"


def test_the_view_of_the_collection_opens_its_map(client):
    assert _preview(client, "/collections/obs")["camera"] == {
        "center": [-77.0, 44.0],
        "zoom": 5.0,
        "minZoom": 0,
    }


def test_a_collection_of_tiles_previews_them_with_their_style(client):
    preview = _preview(client, "/collections/places")
    style = preview["styles"][0]

    assert (preview["kind"], style["name"]) == ("tiles", "Default")
    assert style["style"]["sources"]["archive"]["url"] == (
        f"{SERVER_URL}/collections/places/tiles/WebMercatorQuad/metadata?f=tilejson"
    )


def test_a_collection_with_a_map_previews_one_image_per_view(client):
    preview = _preview(client, "/collections/roads")

    assert preview["kind"] == "image"
    assert preview["maps"] == [
        {"name": "Default", "url": f"{SERVER_URL}/collections/roads/map"},
        {"name": "night", "url": f"{SERVER_URL}/collections/roads/styles/night/map"},
    ]
    assert (preview["maxSize"], preview["camera"]["minZoom"]) == (1024, 2)


def test_a_tile_source_that_fails_falls_back_to_the_extent(client):
    r = _page(client, "/collections/lost")

    assert r.status_code == 200
    preview = island_config(r.text, "fga-map")
    assert (preview["kind"], preview["bbox"]) == ("extent", [6.6, 36.6, 18.5, 47.1])


def test_the_page_leads_to_what_the_collection_offers(client):
    lakes = _page(client, "/collections/lakes").text
    places = _page(client, "/collections/places").text

    assert f'<a href="{SERVER_URL}/collections/lakes/items?f=html">Items</a>' in lakes
    assert f'<a href="{SERVER_URL}/collections/lakes/queryables?f=html">Queryables</a>' in lakes
    assert f'<a href="{SERVER_URL}/collections/lakes/schema?f=html">Schema</a>' in lakes
    assert f'<a href="{SERVER_URL}/collections/places/tiles?f=html">Tilesets</a>' in places


def test_the_page_states_the_facts_of_the_collection(client):
    html = _page(client, "/collections/lakes").text

    assert "<dt>Item type</dt><dd>feature</dd>" in html
    assert "<dt>Spatial extent</dt><dd>-180, -90, 180, 90</dd>" in html
    assert '<a href="http://www.naturalearthdata.com/">information</a>' in html
    assert '<span class="badge">Features</span>' in html


def test_the_license_has_a_heading_of_its_own(client):
    html = _page(client, "/collections/lakes").text

    assert f'<a href="{LICENSE}">CC-BY 4.0</a>' in section(html, "License")


def test_features_list_their_reference_systems_and_the_epoch_of_their_storage(client):
    html = _page(client, "/collections/lakes").text

    assert f'<a href="{CRS84}">{CRS84}</a>' in section(html, "Reference systems")
    assert "<dt>Coordinate epoch</dt><dd>2017.23</dd>" in html


def test_the_collection_is_a_dataset_in_json_ld(client):
    dataset = jsonld(_page(client, "/collections/lakes").text)

    assert (dataset["@context"], dataset["@type"], dataset["name"]) == (
        "https://schema.org",
        "Dataset",
        "Large Lakes",
    )


def test_the_map_island_and_its_style_are_linked(client):
    html = _page(client, "/collections/lakes").text

    assert f'<script type="module" src="{SERVER_URL}/_html/assets/map-8b0c.js"></script>' in html
    assert f'<link rel="stylesheet" href="{SERVER_URL}/_html/assets/map-8b0c.css">' in html


def test_the_crumbs_lead_back_to_the_collections(client):
    html = _page(client, "/collections/lakes").text

    assert (
        f'<a href="{SERVER_URL}/collections?f=html">Collections</a> / <span>Large Lakes</span>'
        in html
    )


def test_an_unknown_collection_keeps_its_json_404(client):
    r = _page(client, "/collections/nope")

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")


def test_the_collection_page_in_italian(client):
    assert "<h2>Esplora</h2>" in _page(client, "/collections/lakes", lang="it").text
