"""The items of a collection: the form of their parameters, the chips, the list, the map.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import re
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.html_fixtures import (
    SERVER_URL,
    config,
    fake_build,
    island_config,
    jsonld,
    native_client,
    with_parquet_lakes,
)

BAIKAL_WIKI = "https://en.wikipedia.org/wiki/Lake_Baikal"

WRONG_CRS = "http://www.opengis.net/def/crs/EPSG/0/9999"

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("items")
    api_config = with_parquet_lakes(config())
    api_config["resources"]["lakes"]["providers"][0]["uri_field"] = "name_alt"
    return native_client(api_config, fake_build(directory / "static"))


def _page(client, path="/collections/lakes/items", **params):
    return client.get(path, params={"f": "html", **params})


def test_the_form_opens_with_the_values_of_the_url(client):
    html = _page(client, name="Lake Baikal", limit="5").text

    assert '<input id="field-name" name="name" type="text" value="Lake Baikal">' in html
    assert '<input id="field-limit" name="limit" type="number" step="any" value="5">' in html


def test_the_queryables_filter_the_items_and_show_as_chips(client):
    html = _page(client, name="Lake Baikal").text

    assert html.count("data-fga-feature=") == 1
    assert "<code>name=Lake Baikal</code>" in html


def test_geojson_gets_no_cql2_field_and_geoparquet_does(client):
    parquet = _page(client, "/collections/lakes-parquet/items").text

    assert 'name="filter"' not in _page(client).text
    assert '<textarea id="field-filter" name="filter" rows="3"></textarea>' in parquet


def test_a_cql2_filter_narrows_the_geoparquet_items(client):
    html = _page(client, "/collections/lakes-parquet/items", filter="area_km2 < 0").text

    assert html.count("data-fga-feature=") == 0
    assert "<code>filter=area_km2 &lt; 0</code>" in html


def test_a_parameter_the_data_ignores_shows_with_a_note(client):
    html = _page(client, datetime="2020-01-01T00:00:00Z").text

    assert (
        '<li class="chip ignored"><code>datetime=2020-01-01T00:00:00Z</code> '
        "<small>the data of this collection does not apply it</small>"
    ) in html


def test_empty_fields_are_left_out(client):
    r = _page(client, bbox="", limit="", name="", datetime="")

    assert r.status_code == 200
    assert '<ul class="chips">' not in r.text


def test_a_refused_bbox_shows_its_message_by_the_field(client):
    r = _page(client, bbox="1,2,3")
    html = r.text
    message = html.index('<p class="field-error" role="alert">bbox should be either 4 values')

    assert (r.status_code, r.headers["content-type"]) == (400, "text/html; charset=utf-8")
    assert html.index('id="field-bbox"') < message < html.index('id="field-limit"')
    assert 'value="1,2,3"' in html


def test_a_message_naming_no_field_shows_above_the_form(client):
    html = _page(client, **{"filter-lang": "klingon"}).text

    assert '<p class="error" role="alert">Invalid filter language' in html
    assert html.index('<p class="error"') < html.index('<form class="filters"')


def test_a_crs_the_data_does_not_offer_shows_by_its_field(client):
    html = _page(client, crs=WRONG_CRS).text

    assert f'<p class="field-error" role="alert">CRS &#39;{WRONG_CRS}&#39; not supported' in html


def test_every_property_of_the_page_is_a_column(client):
    html = _page(client, limit=2).text
    table = html[html.index('<table class="data items">') :]

    assert "<th>scalerank</th>" in table
    assert "<th>featureclass</th>" in table
    assert '<tr data-fga-feature="0">' in table
    assert "<td>Lake</td>" in table


def test_the_uri_field_links_out(client):
    html = _page(client, limit=1).text

    assert f'<td><a href="{BAIKAL_WIKI}">{BAIKAL_WIKI}</a></td>' in html


def test_an_empty_page_says_so(client):
    assert '<p class="results">No items</p>' in _page(client, name="Nowhere").text


def test_the_map_draws_the_features_of_the_page(client):
    html = _page(client, limit="3").text
    preview = island_config(html, "fga-map")

    assert (preview["kind"], preview["camera"]["fitData"]) == ("features", True)
    assert len(preview["data"]["features"]) == 3 == html.count("data-fga-feature=")


def test_the_pager_follows_the_links_of_the_json(client):
    found = re.search(r'<a rel="next" href="([^"]+)">', _page(client, limit="5").text)

    assert found is not None
    query = parse_qs(urlsplit(found.group(1).replace("&amp;", "&")).query)
    assert (query["limit"], query["offset"], query["f"]) == (["5"], ["5"], ["html"])


def test_the_items_are_an_item_list_in_json_ld(client):
    found = jsonld(_page(client, limit="2").text)

    assert (found["@type"], found["numberOfItems"]) == ("ItemList", 2)
    assert found["itemListElement"][0]["url"] == f"{SERVER_URL}/collections/lakes/items/0?f=html"


def test_the_language_stays_when_the_form_is_sent(client):
    html = _page(client, lang="it").text

    assert '<input type="hidden" name="lang" value="it">' in html
    assert "<summary>Avanzate</summary>" in html


def test_an_unknown_collection_keeps_its_json_404(client):
    r = _page(client, "/collections/nope/items")

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")


@pytest.mark.parametrize(
    "crs",
    ["http://www.opengis.net/def/crs/EPSG/0/3857", "http://www.opengis.net/def/crs/EPSG/0/4326"],
)
@pytest.mark.parametrize("path", ["/collections/lakes/items", "/collections/lakes/items/0"])
def test_a_page_in_another_crs_draws_its_json_in_longitude_and_latitude(tmp_path, crs, path):
    api_config = config()
    api_config["resources"]["lakes"]["providers"][0]["crs"] = [CRS84, crs]
    client = native_client(api_config, fake_build(tmp_path))

    r = client.get(path, params={"f": "html", "crs": crs, "limit": 2})
    data = island_config(r.text, "fga-map")["data"]

    assert r.status_code == 200
    assert isinstance(data, str)
    assert "crs=" not in data
    assert "f=json" in data
