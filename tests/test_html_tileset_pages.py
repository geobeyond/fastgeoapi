"""The tilesets of a collection, and one tileset with its template and its TileJSON.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    SERVER_URL,
    config,
    fake_build,
    island_config,
    native_client,
    section,
    with_tiles,
)

TILESET = "/collections/places/tiles/WebMercatorQuad"
TEMPLATE = "/collections/places/tiles/WebMercatorQuad/{tileMatrix}/{tileRow}/{tileCol}?f=mvt"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("tilesets")
    return native_client(with_tiles(config(), directory), fake_build(directory / "static"))


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


@pytest.mark.parametrize("path", [TILESET, f"{TILESET}/metadata"])
def test_the_tileset_lists_its_metadata(client, path):
    metadata = section(_page(client, path).text, "Metadata")

    assert "<td><code>accessConstraints</code></td><td>unclassified</td>" in metadata
    assert "<td><code>description</code></td><td>Places as vector tiles</td>" in metadata


def test_the_tilesets_are_listed_with_their_pages(client):
    html = _page(client, "/collections/places/tiles").text

    assert "<h1>Tilesets of Places</h1>" in html
    assert f'<td><a href="{SERVER_URL}{TILESET}?f=html">' in html
    assert "<td>WebMercatorQuad</td><td>vector</td>" in html


def test_a_tileset_shows_its_template_and_its_tilejson(client):
    html = _page(client, TILESET).text

    assert f"{TEMPLATE}</code></pre>" in html
    assert f'<a href="{SERVER_URL}{TILESET}/metadata?f=tilejson">' in html
    assert (
        f'<a href="{SERVER_URL}/TileMatrixSets/WebMercatorQuad?f=html">WebMercatorQuad</a>' in html
    )


def test_the_tileset_map_draws_the_tiles(client):
    assert island_config(_page(client, TILESET).text, "fga-map")["kind"] == "tiles"


def test_the_metadata_path_is_the_same_page(client):
    r = _page(client, f"{TILESET}/metadata")

    assert (r.status_code, r.headers["content-type"]) == (200, "text/html; charset=utf-8")
    assert "<h1>Tileset WebMercatorQuad of Places</h1>" in r.text


def test_the_crumbs_lead_back_to_the_tilesets(client):
    html = _page(client, TILESET).text

    assert (
        f'<a href="{SERVER_URL}/collections/places/tiles?f=html">Tilesets</a>'
        " / <span>WebMercatorQuad</span>"
    ) in html


def test_the_tilejson_keeps_answering_json(client):
    r = client.get(f"{TILESET}/metadata", params={"f": "tilejson"})

    assert r.json()["tilejson"] == "3.0.0"
