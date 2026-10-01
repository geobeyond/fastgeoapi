"""A collection lists items only when a feature or record provider serves them."""

import pytest

from tests.pmtiles_fixtures import TILE_BYTES, raster_archive, write_archive
from tests.test_tiles_async_route import _client, _collection, _config

MVT = "application/vnd.mapbox-vector-tile"


def _pmtiles(path, *, name: str = "pbf", mimetype: str = MVT) -> dict:
    return {
        "type": "tile",
        "name": "app.provider.pmtiles.PMTilesProvider",
        "data": str(path),
        "options": {"zoom": {"min": 0, "max": 0}, "schemes": ["WebMercatorQuad"]},
        "format": {"name": name, "mimetype": mimetype},
    }


LAKES = {
    "type": "feature",
    "name": "GeoJSON",
    "data": "tests/data/ne_110m_lakes.geojson",
    "id_field": "id",
    "title_field": "name",
}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    base = tmp_path_factory.mktemp("collections")
    vector = write_archive(base / "places.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})
    webp = raster_archive(base / "flowers.pmtiles", kind="WEBP")
    png = raster_archive(base / "shaded.pmtiles", kind="PNG")
    config = _config(
        {
            "places": _collection("Places", [_pmtiles(vector)]),
            # WebP is neither png nor jpeg, the two formats pygeoapi knows are raster.
            "flowers": _collection("Flowers", [_pmtiles(webp, name="webp", mimetype="image/webp")]),
            # The tiles come first, so pygeoapi describes the collection from them.
            "lakes": _collection("Lakes", [_pmtiles(vector), LAKES]),
            "shaded": _collection(
                "Shaded lakes", [_pmtiles(png, name="png", mimetype="image/png"), LAKES]
            ),
        }
    )
    return _client(config)


def _items(collection: dict) -> list[dict]:
    return [link for link in collection["links"] if link["rel"] == "items"]


@pytest.mark.parametrize("name", ["places", "flowers"])
def test_a_collection_of_tiles_alone_lists_no_items(client, name):
    collection = client.get(f"/collections/{name}", params={"f": "json"}).json()

    assert _items(collection) == []
    assert "itemType" not in collection


def test_the_list_of_collections_lists_items_only_where_they_are_served(client):
    listed = client.get("/collections", params={"f": "json"}).json()["collections"]
    collections = {collection["id"]: collection for collection in listed}

    assert _items(collections["places"]) == []
    assert _items(collections["flowers"]) == []
    assert _items(collections["lakes"])


def test_tiles_beside_features_keep_the_items(client):
    collection = client.get("/collections/lakes", params={"f": "json"}).json()

    hrefs = [link["href"] for link in _items(collection)]
    assert hrefs
    assert all("/collections/lakes/items" in href for href in hrefs)
    assert client.get("/collections/lakes/items", params={"f": "json"}).status_code == 200


@pytest.mark.parametrize("name", ["lakes", "shaded"])
def test_the_item_type_is_that_of_the_provider_serving_the_items(client, name):
    collection = client.get(f"/collections/{name}", params={"f": "json"}).json()

    assert collection["itemType"] == "feature"


def test_raster_tiles_beside_features_still_list_the_items(client):
    collection = client.get("/collections/shaded", params={"f": "json"}).json()

    assert {link["type"] for link in _items(collection)} >= {
        "application/geo+json",
        "application/ld+json",
        "text/html",
    }
    assert client.get("/collections/shaded/items", params={"f": "json"}).status_code == 200


@pytest.mark.parametrize("name", ["lakes", "shaded"])
def test_tiles_beside_features_list_the_items_as_csv_too(client, name):
    collection = client.get(f"/collections/{name}", params={"f": "json"}).json()

    assert any(link["type"].startswith("text/csv") for link in _items(collection))


def test_the_html_page_offers_to_browse_the_items_beside_tiles(client):
    page = client.get("/collections/lakes", params={"f": "html"}).text

    assert "Browse through the items of" in page


def test_the_html_page_links_no_items_for_tiles_alone(client):
    page = client.get("/collections/places", params={"f": "html"}).text

    assert "/collections/places/items" not in page


def test_the_json_ld_description_names_no_items_for_tiles_alone(client):
    document = client.get("/collections/places", params={"f": "jsonld"}).text

    assert "/collections/places/items" not in document
