"""Every native page: the same head, headers and JSON-LD.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import re

import pytest
from markupsafe import escape

from tests.html_fixtures import (
    RUNNING_JOB,
    SERVER_URL,
    add_running_job,
    config,
    fake_build,
    island_config,
    jsonld,
    native_client,
    with_coverage,
    with_echo,
    with_edr,
    with_jobs,
    with_map,
    with_parquet_lakes,
    with_stac,
    with_tiles,
)

PATHS = [
    "/",
    "/conformance",
    "/collections",
    "/collections/lakes/queryables",
    "/collections/lakes/schema",
    "/TileMatrixSets",
    "/TileMatrixSets/WebMercatorQuad",
    "/openapi",
    "/processes",
    "/processes/hello-world",
    "/jobs",
    f"/jobs/{RUNNING_JOB}",
]

MAP_PATHS = [
    "/collections/lakes",
    "/collections/lakes/items",
    "/collections/lakes/items/0",
    "/collections/lakes-parquet/items",
    "/collections/places",
    "/collections/places/tiles",
    "/collections/places/tiles/WebMercatorQuad",
    "/collections/roads",
    "/collections/dem/coverage",
    "/collections/weather/instances",
    "/collections/weather/instances/2026",
    "/collections/weather/position",
    "/stac/catalog/rome",
]

PATHS = [*PATHS, *MAP_PATHS, "/stac", "/stac/catalog"]

# The pages whose pygeoapi template lists every link of the JSON.
LINKED_PATHS = [
    "/collections/lakes",
    "/collections/roads",
    "/collections/places",
    "/collections/dem",
    "/collections/weather",
    "/collections/lakes/items/0",
    "/collections/weather/instances/2026",
    "/processes/hello-world",
    f"/jobs/{RUNNING_JOB}",
]

OPENING = re.compile(
    r'<div class="split">\s*<section class="panel">.*?</section>\s*<fga-map>', re.DOTALL
)
"""A page's first block, then its map, side by side in the opening grid."""


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("every")
    add_running_job(directory)
    api_config = with_echo(with_jobs(with_tiles(config(), directory), directory))
    api_config = with_coverage(with_map(with_parquet_lakes(api_config), directory), directory)
    api_config = with_stac(with_edr(api_config))
    return native_client(api_config, fake_build(directory / "static"))


@pytest.mark.parametrize("path", PATHS)
def test_every_page_has_its_head_its_headers_and_its_json_ld(client, path):
    r = client.get(path, params={"f": "html", "lang": "it"})

    assert (r.status_code, r.headers["content-type"]) == (200, "text/html; charset=utf-8")
    assert (r.headers["content-language"], r.headers["vary"]) == (
        "it-IT",
        "Accept, Accept-Language",
    )
    assert r.headers["link"].startswith(f"<{SERVER_URL}")
    assert f'<link rel="canonical" href="{SERVER_URL}' in r.text
    assert '<html lang="it-IT" dir="ltr">' in r.text
    found = jsonld(r.text)
    assert found["@context"]
    assert found.get("@type") or found.get("type")


@pytest.mark.parametrize("path", MAP_PATHS)
def test_every_map_island_says_what_it_draws(client, path):
    island = island_config(client.get(path, params={"f": "html"}).text, "fga-map")

    assert island["kind"] in ("tiles", "image", "features", "extent")
    assert "minZoom" in island["camera"]


@pytest.mark.parametrize("path", LINKED_PATHS)
def test_every_link_of_the_json_is_on_the_page(client, path):
    links = client.get(path, params={"f": "json"}).json()["links"]
    page = client.get(path, params={"f": "html"}).text

    missing = [
        link["href"]
        for link in links
        if link.get("href") and f'href="{escape(link["href"])}"' not in page
    ]

    assert links
    assert missing == []


@pytest.mark.parametrize("path", MAP_PATHS)
def test_every_map_sits_beside_the_first_block_of_its_page(client, path):
    html = client.get(path, params={"f": "html"}).text

    assert OPENING.search(html), html[:3000]
    assert 'class="mapcol"' not in html


def test_the_items_run_below_the_opening_across_the_page(client):
    html = client.get("/collections/lakes/items", params={"f": "html"}).text
    opening, _, rest = html.partition('<section class="rest">')

    assert '<form class="filters"' in opening
    assert '<table class="data items">' in rest
    assert '<form class="filters"' not in rest


def test_the_first_block_of_an_item_is_its_properties_and_its_links_follow(client):
    html = client.get("/collections/lakes/items/0", params={"f": "html"}).text
    opening, _, rest = html.partition('<section class="rest">')

    assert '<table class="data">' in opening
    assert "<h2>Links</h2>" in rest
