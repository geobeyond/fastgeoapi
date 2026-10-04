"""The API documentation page: the viewer and the document it opens.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import pytest

from tests.html_fixtures import SERVER_URL, config, fake_build, island_config, native_client


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    return native_client(config(), fake_build(tmp_path_factory.mktemp("static")))


def _page(client, **params):
    return client.get("/openapi", params={"f": "html", **params}).text


def test_swagger_ui_opens_the_json_document_by_default(client):
    html = _page(client)

    assert island_config(html, "fga-api-docs") == {
        "ui": "swagger",
        "url": f"{SERVER_URL}/openapi?f=json",
    }
    assert (
        f'<script type="module" src="{SERVER_URL}/_html/assets/api-docs-77aa.js"></script>' in html
    )
    assert f'<link rel="stylesheet" href="{SERVER_URL}/_html/assets/api-docs-77aa.css">' in html


def test_redoc_on_request_with_a_way_back(client):
    html = _page(client, ui="redoc")

    assert island_config(html, "fga-api-docs")["ui"] == "redoc"
    assert f'href="{SERVER_URL}/openapi?f=html&amp;ui=swagger"' in html


def test_the_swagger_page_points_to_redoc(client):
    assert f'href="{SERVER_URL}/openapi?f=html&amp;ui=redoc"' in _page(client)
