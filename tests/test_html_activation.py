"""Which pages the sub-app serves: pygeoapi's by default, fastgeoapi's when asked.

``app.*`` is imported at the top of this module.
"""

import importlib
import sys
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from app.config.app import DevConfig, ProdConfig
from app.html import activation
from app.html.package import HtmlPagesUnavailableError
from app.html.pages import NativePages
from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
from tests.html_fixtures import config, fake_build, native_client


def _settings(pages, templates=None):
    return SimpleNamespace(FASTGEOAPI_HTML_PAGES=pages, FASTGEOAPI_HTML_TEMPLATES=templates)


@pytest.mark.parametrize("settings_class", [DevConfig, ProdConfig])
def test_pygeoapis_pages_are_the_default(settings_class):
    fields = settings_class.model_fields

    assert fields["FASTGEOAPI_HTML_PAGES"].default == "pygeoapi"
    assert fields["FASTGEOAPI_HTML_TEMPLATES"].default is None


def test_pygeoapi_in_the_settings_keeps_pygeoapis_pages():
    assert activation.pages_from(_settings("pygeoapi")) is None


def test_native_in_the_settings_gives_fastgeoapis_pages():
    assert isinstance(activation.pages_from(_settings("native")), NativePages)


def test_native_without_the_package_names_the_extra_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "fastgeoapi_html", None)

    with pytest.raises(HtmlPagesUnavailableError, match=r"fastgeoapi\[html\]"):
        activation.pages_from(_settings("native"))


def test_the_default_follows_fastgeoapis_settings(monkeypatch):
    # ``default_pages`` imports the settings when it runs; after a module that
    # purges ``app.*``, that is a fresh module, not the one this file bound at
    # import. Patch the live one.
    live = importlib.import_module("app.config.app").configuration
    monkeypatch.setattr(live, "FASTGEOAPI_HTML_PAGES", "native")

    assert isinstance(activation.default_pages(), NativePages)


def test_without_a_choice_the_sub_app_serves_pygeoapis_pages():
    api_config = config()
    client = TestClient(build_pygeoapi_subapp(api_config, build_openapi(api_config)))

    assert "bootstrap" in client.get("/", params={"f": "html"}).text


def test_native_pages_replace_pygeoapis(tmp_path):
    r = native_client(config(), fake_build(tmp_path)).get("/", params={"f": "html"})

    assert r.status_code == 200
    assert "bootstrap" not in r.text
    assert '<header class="bar">' in r.text


def test_the_compiled_assets_are_cached_for_good(tmp_path):
    r = native_client(config(), fake_build(tmp_path)).get("/_html/assets/style-4f2a.css")

    assert (r.status_code, r.headers["cache-control"]) == (
        200,
        "public, max-age=31536000, immutable",
    )


def test_without_a_build_the_pages_render_without_assets(tmp_path):
    r = native_client(config(), tmp_path).get("/", params={"f": "html"})

    assert r.status_code == 200
    assert "/_html/" not in r.text


def test_a_template_in_the_configured_directory_replaces_the_packages(tmp_path):
    (tmp_path / "landing.html").write_text(
        '{% extends "_layout.html" %}{% block content %}<p>our landing</p>{% endblock %}\n'
    )
    pages = activation.pages_from(_settings("native", str(tmp_path)))
    api_config = config()
    client = TestClient(build_pygeoapi_subapp(api_config, build_openapi(api_config), pages=pages))

    assert "<p>our landing</p>" in client.get("/", params={"f": "html"}).text
