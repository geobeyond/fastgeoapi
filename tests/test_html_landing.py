"""The landing page: the service, its sections and its collections.

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
    with_jobs,
    with_stac,
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("landing")
    api_config = with_stac(with_jobs(config(), directory))
    return native_client(api_config, fake_build(directory / "static"))


def _landing(client, **params):
    return client.get("/", params={"f": "html", **params}).text


def test_the_page_names_the_service_and_says_what_it_offers(client):
    html = _landing(client)

    assert "<title>pygeoapi default instance</title>" in html
    assert "<h1>pygeoapi default instance</h1>" in html
    assert '<p class="lead">pygeoapi provides an API to geospatial data</p>' in html


def test_the_sections_lead_to_their_html_pages(client):
    html = _landing(client)

    for path in ("collections", "processes", "openapi", "conformance"):
        assert f'href="{SERVER_URL}/{path}?f=html"' in html
    assert "TileMatrixSets" not in html  # no tile collection in this configuration


def test_the_sections_lead_to_the_jobs_and_to_stac(client):
    html = _landing(client)

    assert f'href="{SERVER_URL}/jobs?f=html"' in html
    assert f'href="{SERVER_URL}/stac?f=html"' in html


def test_the_keywords_of_the_service_follow_the_language(client):
    assert '<span class="keyword">geospatial</span>' in _landing(client)
    assert '<span class="keyword">géospatiale</span>' in _landing(client, lang="fr-CA")


def test_the_service_states_its_terms_license_provider_and_contact(client):
    about = section(_landing(client), "About this service")
    license_url = "https://creativecommons.org/licenses/by/4.0/"

    assert f'<dt>Terms of service</dt><dd><a href="{license_url}">{license_url}</a></dd>' in about
    assert f'<a href="{license_url}">CC-BY 4.0 license</a>' in about
    assert '<a href="https://pygeoapi.io">Organization Name</a>' in about
    assert "Mailing Address, City, Administrative Area, Zip or Postal Code, Country" in about
    assert '<a href="mailto:you@example.org">you@example.org</a>' in about
    assert "<dd>Mo-Fr 08:00-17:00</dd>" in about


def test_the_api_definition_offers_swagger_redoc_and_the_document(client):
    api = section(_landing(client), "API definition")

    assert f'<a href="{SERVER_URL}/openapi?f=html">Swagger UI</a>' in api
    assert f'<a href="{SERVER_URL}/openapi?f=html&amp;ui=redoc">ReDoc</a>' in api
    assert f'<a href="{SERVER_URL}/openapi">OpenAPI document</a>' in api


def test_each_collection_is_a_card_with_what_it_serves(client):
    html = _landing(client)

    assert f'<h3><a href="{SERVER_URL}/collections/lakes?f=html">Large Lakes</a></h3>' in html
    assert '<span class="badge">Features</span>' in html


def test_a_title_in_several_languages_follows_the_page(client):
    assert "Grands Lacs" in _landing(client, lang="fr-CA")


def test_the_service_is_a_schema_org_data_catalog(client):
    catalog = jsonld(_landing(client))

    assert (catalog["@type"], catalog["name"]) == ("DataCatalog", "pygeoapi default instance")


def test_the_head_carries_the_canonical_url_and_the_stylesheet(client):
    html = _landing(client)

    assert f'<link rel="canonical" href="{SERVER_URL}?f=html">' in html
    assert f'<link rel="stylesheet" href="{SERVER_URL}/_html/assets/style-4f2a.css">' in html


def test_in_italian_the_interface_is_italian(client):
    html = _landing(client, lang="it")

    assert '<html lang="it-IT" dir="ltr">' in html
    assert "<h2>Collezioni</h2>" in html
    assert '<span class="badge">Feature</span>' in html


def test_the_logo_and_the_icon_default_to_pygeoapis(client):
    html = _landing(client)

    assert f'src="{SERVER_URL}/static/img/logo.png"' in html
    assert f'href="{SERVER_URL}/static/img/favicon.ico"' in html


def test_the_configured_logo_and_icon_win(tmp_path):
    api_config = config()
    api_config["server"]["logo"] = "https://example.org/logo.svg"
    api_config["server"]["icon"] = "https://example.org/icon.png"

    html = native_client(api_config, fake_build(tmp_path)).get("/", params={"f": "html"}).text

    assert 'src="https://example.org/logo.svg"' in html
    assert 'href="https://example.org/icon.png"' in html


def test_text_from_the_configuration_is_never_markup(tmp_path):
    api_config = config()
    title = "Lakes </script><script>alert(1)</script>"
    api_config["metadata"]["identification"]["title"] = title

    html = native_client(api_config, fake_build(tmp_path)).get("/", params={"f": "html"}).text

    assert "<script>alert(1)</script>" not in html
    assert jsonld(html)["name"] == title


def test_a_hidden_collection_has_no_card(tmp_path):
    api_config = config()
    api_config["resources"]["lakes"]["visibility"] = "hidden"

    html = native_client(api_config, fake_build(tmp_path)).get("/", params={"f": "html"}).text

    assert f'href="{SERVER_URL}/collections/lakes?f=html"' not in html
    assert f'href="{SERVER_URL}/collections/obs?f=html"' in html


def test_without_processes_the_landing_offers_neither_processes_nor_jobs(tmp_path):
    api_config = with_jobs(config(), tmp_path)
    del api_config["resources"]["hello-world"]

    html = (
        native_client(api_config, fake_build(tmp_path / "static"))
        .get("/", params={"f": "html"})
        .text
    )

    assert f"{SERVER_URL}/processes?f=html" not in html
    assert f"{SERVER_URL}/jobs?f=html" not in html
