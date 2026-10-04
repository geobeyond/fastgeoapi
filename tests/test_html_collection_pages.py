"""The collections, their queryables and their schema.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    SERVER_URL,
    config,
    fake_build,
    jsonld,
    native_client,
    section,
    with_parquet_lakes,
    with_records,
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return native_client(config(), fake_build(tmp_path_factory.mktemp("static")))


@pytest.fixture(scope="module")
def wider(tmp_path_factory):
    directory = tmp_path_factory.mktemp("wider")
    api_config = with_records(with_parquet_lakes(config()), directory)
    return native_client(api_config, fake_build(directory / "static"))


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


def test_each_collection_is_a_card_with_its_keywords(client):
    html = _page(client, "/collections").text

    assert f'<h3><a href="{SERVER_URL}/collections/obs?f=html">Observations</a></h3>' in html
    assert '<span class="keyword">monitoring</span>' in html
    assert '<span class="badge">Features</span>' in html


def test_the_collections_are_datasets_of_the_catalog(client):
    catalog = jsonld(_page(client, "/collections").text)

    assert catalog["@type"] == "DataCatalog"
    assert [dataset["name"] for dataset in catalog["dataset"]] == ["Observations", "Large Lakes"]


def test_the_queryables_are_a_table_of_properties(client):
    html = _page(client, "/collections/lakes/queryables").text

    assert "<title>Queryables of Large Lakes · pygeoapi default instance</title>" in html
    assert "<td><code>scalerank</code></td><td>integer</td><td></td>" in html
    assert "<td><code>geometry</code></td><td>geometry-any</td><td>primary-geometry</td>" in html


def test_the_crumbs_lead_back_to_the_collection(client):
    html = _page(client, "/collections/lakes/queryables").text

    assert (
        f'<a href="{SERVER_URL}/collections/lakes?f=html">Large Lakes</a> / <span>Queryables</span>'
        in html
    )


def test_the_schema_shows_the_properties_of_the_items(client):
    html = _page(client, "/collections/lakes/schema").text

    assert "<h1>Schema of Large Lakes</h1>" in html
    assert "<td><code>name</code></td><td>string</td>" in html


def test_data_and_records_are_listed_apart(wider):
    html = _page(wider, "/collections").text

    assert f'href="{SERVER_URL}/collections/lakes?f=html"' in section(html, "Data collections")
    records = section(html, "Record collections")
    assert f'href="{SERVER_URL}/collections/records?f=html"' in records
    assert "/collections/lakes?" not in records


def test_a_format_shows_beside_its_type(wider):
    html = _page(wider, "/collections/lakes-parquet/schema").text

    assert "<td><code>observed_at</code></td><td>string (date-time)</td>" in html


def test_the_queryables_and_the_schema_show_the_keywords(client):
    for path in ("/collections/lakes/queryables", "/collections/lakes/schema"):
        assert '<span class="keyword">lakes</span>' in _page(client, path).text


def test_the_queryables_in_italian(client):
    assert (
        "<h1>Proprietà interrogabili di Large Lakes</h1>"
        in _page(client, "/collections/lakes/queryables", lang="it").text
    )


def test_an_unknown_collection_keeps_its_json_404(client):
    r = _page(client, "/collections/nope/schema")

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")
