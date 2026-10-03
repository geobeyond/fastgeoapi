"""The conformance page and the tile matrix set pages.

``app.*`` is imported at the top of ``tests.html_fixtures``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import SERVER_URL, config, fake_build, native_client, with_tiles

FEATURES_CORE = "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core"
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("service")
    return native_client(with_tiles(config(), directory), fake_build(directory / "static"))


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


def test_the_conformance_classes_are_grouped_by_standard(client):
    html = _page(client, "/conformance").text

    assert "<h2>ogcapi-features-1 1.0</h2>" in html
    assert f'<li><a href="{FEATURES_CORE}">{FEATURES_CORE}</a></li>' in html


def test_the_conformance_page_in_italian(client):
    assert "<h1>Conformità</h1>" in _page(client, "/conformance", lang="it").text


def test_the_tile_matrix_sets_link_their_pages(client):
    html = _page(client, "/TileMatrixSets").text

    assert (
        f'<a href="{SERVER_URL}/TileMatrixSets/WebMercatorQuad?f=html">WebMercatorQuad</a>' in html
    )


def test_a_tile_matrix_set_shows_its_reference_system_and_its_levels(client):
    html = _page(client, "/TileMatrixSets/WebMercatorQuad").text

    assert f'<a href="{WEB_MERCATOR}">{WEB_MERCATOR}</a>' in html
    assert "<td>0</td><td>559,082,264.029</td>" in html


def test_its_numbers_follow_the_page_language(client):
    html = _page(client, "/TileMatrixSets/WebMercatorQuad", lang="it").text

    assert "<td>0</td><td>559.082.264,029</td>" in html


def test_an_unknown_tile_matrix_set_keeps_pygeoapis_answer(client):
    r = _page(client, "/TileMatrixSets/Nope")

    assert (r.status_code, r.headers["content-type"]) == (400, "application/json")


def test_with_tiles_the_landing_page_offers_them(client):
    html = _page(client, "/").text

    assert f'href="{SERVER_URL}/TileMatrixSets?f=html"' in html
    assert '<span class="badge">Vector tiles</span>' in html
