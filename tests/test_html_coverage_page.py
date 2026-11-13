"""The page of a coverage: its grid and bands, the download narrowed by its parameters.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    SERVER_URL,
    config,
    fake_build,
    island_config,
    native_client,
    with_coverage,
)

COVERAGE = "/collections/dem/coverage"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("coverage")
    return native_client(with_coverage(config(), directory), fake_build(directory / "static"))


def _page(client, path=COVERAGE, **params):
    return client.get(path, params={"f": "html", **params})


def test_the_page_describes_the_grid_and_the_bands(client):
    html = _page(client).text

    assert "<h1>Coverage of DEM</h1>" in html
    assert "<dt>Grid</dt><dd>4 \u00d7 4</dd>" in html
    assert "<dt>Resolution</dt><dd>0.125 \u00d7 0.1</dd>" in html
    assert "<tr><td><code>1</code></td><td></td><td>number</td></tr>" in html


def test_the_downloads_carry_the_narrowed_parameters(client):
    html = _page(client, bbox="12.2,41.7,12.4,41.9", subset="").text
    narrowed = f"{SERVER_URL}{COVERAGE}?bbox=12.2%2C41.7%2C12.4%2C41.9"

    assert f'<a class="pill" href="{narrowed}&amp;f=GTiff">GeoTIFF</a>' in html
    assert f'<a class="pill" href="{narrowed}&amp;f=json">CoverageJSON</a>' in html
    assert 'value="12.2,41.7,12.4,41.9"' in html


def test_the_map_shows_the_extent(client):
    preview = island_config(_page(client).text, "fga-map")

    assert (preview["kind"], preview["bbox"]) == ("extent", [12.2, 41.7, 12.7, 42.1])


def test_the_coverage_keeps_answering_its_formats(client):
    r = client.get(COVERAGE, params={"f": "json"})

    assert r.headers["content-type"] == "application/prs.coverage+json"


def test_an_unknown_collection_keeps_its_json_404(client):
    r = _page(client, "/collections/nope/coverage")

    assert (r.status_code, r.headers["content-type"]) == (404, "application/json")


def test_the_coverage_page_in_italian(client):
    assert "<h2>Scarica</h2>" in _page(client, lang="it").text
