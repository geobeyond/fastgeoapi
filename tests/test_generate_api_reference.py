"""The API reference pages generated from the example OpenAPI document."""

import importlib.util
import re
import tomllib
from pathlib import Path

import pytest
from pygeoapi.util import yaml_load


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "generate_api_reference", Path("scripts/generate_api_reference.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOCUMENT = {
    "openapi": "3.0.2",
    "info": {"title": "example", "version": "1"},
    "tags": [
        {"name": "server", "description": "The server."},
        {"name": "lakes", "description": "Lakes of the world."},
    ],
    "paths": {
        "/": {"get": {"operationId": "getLandingPage", "summary": "Landing", "tags": ["server"]}},
        "/collections/lakes/items": {
            "get": {
                "operationId": "getLakesFeatures",
                "summary": "Lakes",
                "tags": ["lakes"],
                "responses": {
                    "200": {
                        "description": "The lakes.",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/lake"}}
                        },
                    }
                },
            }
        },
    },
    "components": {"schemas": {"lake": {"type": "object"}}},
}


def _count_operations(document: dict) -> int:
    methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    return sum(len(methods & set(item)) for item in document["paths"].values())


def test_every_operation_has_a_page(script, tmp_path):
    written = script.write_reference(DOCUMENT, tmp_path)

    pages = [p for p in written if p.name.startswith("operation-")]
    assert len(pages) == _count_operations(DOCUMENT)
    assert all(p.is_relative_to(tmp_path / script.REFERENCE_DIR) for p in pages)


def test_every_link_between_the_pages_resolves(script, tmp_path):
    written = script.write_reference(DOCUMENT, tmp_path)

    for page in (p for p in written if p.suffix == ".md"):
        for target in re.findall(r"\]\(([^)#\s]+\.md)", page.read_text()):
            assert (page.parent / target).resolve().exists(), (page, target)


def test_the_theme_assets_are_copied(script, tmp_path):
    script.write_reference(DOCUMENT, tmp_path)

    assert (tmp_path / "stylesheets/mkdocs-openapi.css").stat().st_size > 0
    assert (tmp_path / "javascripts/mkdocs-openapi.js").stat().st_size > 0


def test_a_new_run_removes_the_pages_of_the_previous_one(script, tmp_path):
    stale = tmp_path / script.REFERENCE_DIR / "gone" / "operation-get-gone.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("# gone")

    script.write_reference(DOCUMENT, tmp_path)

    assert not stale.exists()


def test_the_nav_lists_a_page_for_every_tag_of_the_example(script):
    with open("pygeoapi-config.yml") as handle:
        resources = _load_config(handle, script)["resources"]
    tags = {"server", *resources}
    nav = tomllib.loads(Path("zensical.toml").read_text())["project"]["nav"]

    entries = _find_section(nav, "API reference (example)")

    assert {Path(path).parent.name for path in entries.values()} >= tags
    assert entries["Overview"] == f"{script.REFERENCE_DIR}/index.md"
    assert entries["Models"] == f"{script.REFERENCE_DIR}/models/index.md"


def _load_config(handle, script):
    with script.set_example_environment():
        return yaml_load(handle)


def _find_section(nav: list, title: str) -> dict[str, str]:
    for item in nav:
        if not isinstance(item, dict):
            continue
        for name, value in item.items():
            if name == title:
                return {k: v for entry in value for k, v in entry.items()}
            if isinstance(value, list):
                found = _find_section(value, title)
                if found:
                    return found
    return {}
