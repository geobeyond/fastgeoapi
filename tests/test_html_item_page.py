"""The page of one item: its properties, its map, its JSON-LD.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    SERVER_URL,
    config,
    fake_build,
    island_config,
    jsonld,
    native_client,
)

BAIKAL = "/collections/lakes/items/0"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("item")
    return native_client(config(), fake_build(directory / "static"))


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


def test_an_item_is_named_by_its_title_field(client):
    assert '<section class="panel">\n    <h1>Lake Baikal</h1>' in _page(client, BAIKAL).text


def test_an_item_without_a_title_field_is_named_by_its_identifier(client):
    html = _page(client, "/collections/obs/items/371").text

    assert '<section class="panel">\n    <h1>371</h1>' in html


def test_its_properties_are_a_table_and_links_are_links(client):
    html = _page(client, BAIKAL).text

    assert "<tr><td><code>scalerank</code></td><td>0</td></tr>" in html
    assert (
        '<td><a href="https://en.wikipedia.org/wiki/Lake_Baikal">'
        "https://en.wikipedia.org/wiki/Lake_Baikal</a></td>"
    ) in html


def test_its_map_draws_it(client):
    preview = island_config(_page(client, BAIKAL).text, "fga-map")

    assert (preview["kind"], preview["camera"]["fitData"]) == ("features", True)
    assert [feature["id"] for feature in preview["data"]["features"]] == [0]


def test_the_item_is_its_own_json_ld(client):
    assert jsonld(_page(client, BAIKAL).text)["@id"] == f"{SERVER_URL}{BAIKAL}"


def test_the_crumbs_lead_back_to_the_items(client):
    assert (
        f'<a href="{SERVER_URL}/collections/lakes/items?f=html">Items</a>'
        " / <span>Lake Baikal</span>"
    ) in _page(client, BAIKAL).text


def test_an_unknown_item_keeps_its_json_404(client):
    r = _page(client, "/collections/lakes/items/999")

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")
