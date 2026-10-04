"""The STAC pages: the root, a catalog, an item with its assets and footprint.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    SERVER_URL,
    config,
    fake_build,
    island_config,
    native_client,
    with_stac,
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("stac")
    return native_client(with_stac(config()), fake_build(directory / "static"))


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


def test_the_root_lists_the_catalogs(client):
    html = _page(client, "/stac").text

    assert "<h1>SpatioTemporal Asset Catalog</h1>" in html
    assert f'<a href="{SERVER_URL}/stac/catalog?f=html">catalog</a>' in html


def test_a_catalog_lists_its_items(client):
    html = _page(client, "/stac/catalog").text

    assert "<h1>Catalog</h1>" in html
    assert f'<a href="{SERVER_URL}/stac/catalog/rome?f=html">rome.tif</a>' in html


def test_an_item_shows_its_assets_and_its_footprint(client):
    html = _page(client, "/stac/catalog/rome").text
    preview = island_config(html, "fga-map")

    assert (
        f'<tr><td><a href="{SERVER_URL}/stac/catalog/rome.tif">default</a></td>'
        "<td>image/tiff</td><td>430</td></tr>"
    ) in html
    assert preview["data"]["features"][0]["geometry"]["type"] == "Polygon"
    assert preview["camera"]["fitData"] is True


def test_an_item_without_a_footprint_has_no_map(client):
    r = _page(client, "/stac/catalog/nowhere")

    assert r.status_code == 200
    assert "<fga-map>" not in r.text
    assert '<div class="split solo">' in r.text


def test_the_crumbs_follow_the_path(client):
    assert (
        f'<a href="{SERVER_URL}/stac?f=html">STAC</a> / '
        f'<a href="{SERVER_URL}/stac/catalog?f=html">catalog</a> / <span>rome</span>'
    ) in _page(client, "/stac/catalog/rome").text


def test_an_unknown_catalog_keeps_its_json_404(client):
    r = _page(client, "/stac/nope")

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")
