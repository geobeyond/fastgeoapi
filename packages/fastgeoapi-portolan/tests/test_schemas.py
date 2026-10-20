"""The JSON Schemas the package ships, and how a schema URL finds its file."""

from __future__ import annotations

import json
from importlib.resources import files

import pytest

from fastgeoapi_portolan.catalog.schema_files import schema_file, schema_resources

COMMIT = "123c65379c7807e8e43fdb62fb0d98e9dd6a2d17"
SCHEMAS = files("fastgeoapi_portolan.catalog.schemas")


def test_the_schemas_ship_with_the_package():
    for path in (
        "stac/1.1.0/collection-spec/json-schema/collection.json",
        "stac/1.0.0/item-spec/json-schema/basics.json",
        "portolan/v0.1.1/schema.json",
        "portolan/v0.2.0/schema.json",
        "extension-registry.json",
    ):
        assert SCHEMAS.joinpath(path).is_file(), path
    assert COMMIT in SCHEMAS.joinpath("SOURCE").read_text()


@pytest.mark.parametrize(
    ("url", "path"),
    [
        (
            "https://schemas.stacspec.org/v1.1.0/collection-spec/json-schema/collection.json",
            "stac/1.1.0/collection-spec/json-schema/collection.json",
        ),
        (
            "https://schemas.stacspec.org/v1.0.0/item-spec/json-schema/basics.json",
            "stac/1.0.0/item-spec/json-schema/basics.json",
        ),
        (
            "https://schemas.portolan-sdi.org/portolan/v0.1.1/schema.json",
            "portolan/v0.1.1/schema.json",
        ),
        (
            "https://schemas.portolan-sdi.org/portolan/v0.1.1/schema.json#",
            "portolan/v0.1.1/schema.json",
        ),
        (
            "https://stac-extensions.github.io/table/v1.2.0/schema.json",
            "extensions/stac-extensions.github.io/table/v1.2.0/schema.json",
        ),
        (
            "https://schemas.portolan-sdi.org/incubating/partition/v1.0.0/schema.json",
            "extensions/schemas.portolan-sdi.org/incubating/partition/v1.0.0/schema.json",
        ),
    ],
)
def test_a_schema_url_maps_to_its_file(url, path):
    found = schema_file(url)

    assert found is not None
    assert found.read_text() == SCHEMAS.joinpath(path).read_text()


def test_an_unknown_schema_url_maps_to_nothing():
    assert schema_file("https://stac-extensions.github.io/table/v9.9.9/schema.json") is None


def test_every_registered_extension_has_its_schema():
    registry = json.loads(SCHEMAS.joinpath("extension-registry.json").read_text())

    missing = [url for url in registry["extensions"].values() if schema_file(url) is None]

    assert missing == []


def test_common_json_is_reachable_by_its_path_and_by_its_id():
    urls = {url for url, _ in schema_resources()}

    assert "https://schemas.stacspec.org/v1.1.0/item-spec/json-schema/common.json" in urls
    assert "https://schemas.stacspec.org/v1.1.0/item-spec/json-schema/commonjson" in urls
