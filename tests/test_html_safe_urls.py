"""A URL from the data is a link only when a browser would open it as a page.

``app.*`` is imported at the top of this module.
"""

import json
import re
from pathlib import Path

import pytest

from app.html.pages import safe_url
from tests.html_fixtures import config, fake_build, native_client

TEMPLATES = Path("packages/fastgeoapi-html/fastgeoapi_html/templates")
TRANSLATED = re.compile(r"{% trans .*?{% endtrans %}", re.DOTALL)
URL_ATTRIBUTE = re.compile(r'(?:href|src|action)="\{\{ (.+?) \}\}')
TRAP = "javascript:alert(document.domain)//"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        " JavaScript:alert(1)",
        "java\tscript:alert(1)",
        "\x01javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
    ],
)
def test_a_url_a_browser_would_run_is_dropped(url):
    assert safe_url(url) == ""


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/a?f=json",
        "http://example.org",
        "mailto:info@example.org",
        "tel:+390612345678",
        "/collections?f=html",
        "items?f=html",
        "#top",
    ],
)
def test_a_url_of_the_web_or_a_relative_one_is_kept(url):
    assert safe_url(url) == url


def test_what_is_not_text_is_no_url():
    assert safe_url(None) == ""
    assert safe_url(42) == ""


def test_every_url_attribute_of_a_template_goes_through_safe_url():
    unguarded = []
    for path in sorted(TEMPLATES.glob("*.html")):
        text = TRANSLATED.sub("", path.read_text())
        unguarded += [
            f"{path.name}: {expression}"
            for expression in URL_ATTRIBUTE.findall(text)
            if "safe_url" not in expression
        ]

    assert unguarded == []


def test_no_template_puts_a_value_in_another_url_attribute():
    # The other attributes a browser reads a URL from. The islands' data-*
    # attributes are read by their scripts, which never navigate to them.
    found = []
    for path in sorted(TEMPLATES.glob("*.html")):
        found += [
            f"{path.name}: {attribute}"
            for attribute in re.findall(
                r'\b(srcset|formaction|poster|cite|ping|background|xlink:href|style)="\{\{',
                path.read_text(),
            )
        ]

    assert found == []


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("trap")
    data = directory / "trap.geojson"
    data.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "id": 1,
                        "properties": {"id": 1, "name": "Trap", "wiki": TRAP},
                        "geometry": {"type": "Point", "coordinates": [12.5, 41.9]},
                    }
                ],
            }
        )
    )
    api_config = config()
    lakes = api_config["resources"]["lakes"]
    api_config["resources"]["trap"] = {
        **lakes,
        "title": "Trap",
        "providers": [{**lakes["providers"][0], "data": str(data), "uri_field": "wiki"}],
    }
    return native_client(api_config, fake_build(directory / "static"))


@pytest.mark.parametrize("path", ["/collections/trap/items", "/collections/trap/items/1"])
def test_a_script_url_in_the_data_is_never_a_link(client, path):
    html = client.get(path, params={"f": "html"}).text

    assert "Trap" in html
    assert 'href="javascript:' not in html.lower()
