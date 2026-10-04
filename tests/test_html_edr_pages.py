"""The EDR pages: the instances, an instance, and a query with its form, tables and map.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    SERVER_URL,
    FakeEDRProvider,
    config,
    fake_build,
    island_config,
    native_client,
    section,
    with_edr,
)

ROME = "POINT(12.5 41.9)"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("edr")
    api_config = with_edr(config())
    api_config["resources"]["weather"]["keywords"] = ["forecast"]
    return native_client(api_config, fake_build(directory / "static"))


def _page(client, path, **params):
    return client.get(path, params={"f": "html", **params})


def test_the_collection_lists_its_parameters_with_their_units(client):
    parameters = section(_page(client, "/collections/weather").text, "Parameters")

    assert "<td><code>temperature</code></td><td>Temperature</td><td>K</td>" in parameters


@pytest.mark.parametrize(
    "path", ["/collections/weather/instances", "/collections/weather/instances/2026"]
)
def test_the_instances_describe_their_collection(client, path):
    html = _page(client, path).text

    assert '<p class="lead">Temperatures</p>' in html
    assert '<span class="keyword">forecast</span>' in html


def test_the_collection_leads_to_its_queries(client):
    html = _page(client, "/collections/weather").text

    assert (
        f'<a href="{SERVER_URL}/collections/weather/position?f=html">Query at a position</a>'
        in html
    )
    assert f'<a href="{SERVER_URL}/collections/weather/instances?f=html">Instances</a>' in html


def test_a_query_without_coordinates_is_a_blank_form(client):
    r = _page(client, "/collections/weather/position")

    assert r.status_code == 200
    assert '<input id="field-coords" name="coords" type="text" value="">' in r.text
    assert 'role="alert"' not in r.text
    assert island_config(r.text, "fga-map")["kind"] == "extent"


def test_a_position_shows_the_values_of_its_parameters(client):
    html = _page(client, "/collections/weather/position", coords=ROME).text
    preview = island_config(html, "fga-map")

    assert (
        "<tr><td><code>temperature</code></td><td>Temperature</td><td>K</td><td>288.4</td></tr>"
        in html
    )
    assert "<tr><td><code>t</code></td><td>2026-10-03T00:00:00Z</td><td>1</td></tr>" in html
    assert preview["data"]["features"][0]["geometry"] == {
        "type": "Point",
        "coordinates": [12.5, 41.9],
    }


def test_wrong_coordinates_show_their_message_by_the_field(client):
    r = _page(client, "/collections/weather/position", coords="POINT(nope)")
    html = r.text

    assert r.status_code == 400
    assert html.index('id="field-coords"') < html.index(
        '<p class="field-error" role="alert">invalid coords parameter</p>'
    )


def test_the_instances_are_listed(client):
    html = _page(client, "/collections/weather/instances").text

    assert f'<a href="{SERVER_URL}/collections/weather/instances/2026?f=html">2026</a>' in html


def test_an_instance_leads_to_its_queries(client):
    html = _page(client, "/collections/weather/instances/2026").text

    assert (
        f'<a href="{SERVER_URL}/collections/weather/instances/2026/position?f=html">'
        "Query at a position</a>"
    ) in html


def test_an_instance_query_names_its_collection(client):
    html = _page(client, "/collections/weather/instances/2026/position", coords=ROME).text

    assert "<h1>Query at a position, Weather, instance 2026</h1>" in html
    assert f'<a href="{SERVER_URL}/collections/weather?f=html">Weather</a>' in html
    assert f'action="{SERVER_URL}/collections/weather/instances/2026/position"' in html


def test_the_fake_source_names_its_temperature():
    # pygeoapi may never ask the fields of this source; the coverage of tests/ needs them read.
    source = FakeEDRProvider({"name": "fake", "type": "edr", "data": "unused"})

    assert source.get_fields()["temperature"]["x-ogc-unit"] == "K"
