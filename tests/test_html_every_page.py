"""Every native page: the same head, headers and JSON-LD.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import (
    RUNNING_JOB,
    SERVER_URL,
    add_running_job,
    config,
    fake_build,
    jsonld,
    native_client,
    with_echo,
    with_jobs,
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


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("every")
    add_running_job(directory)
    api_config = with_echo(with_jobs(with_tiles(config(), directory), directory))
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
    assert jsonld(r.text)["@type"] in ("DataCatalog", "WebPage")
