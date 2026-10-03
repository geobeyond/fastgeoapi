"""fastgeoapi's own keys in a pygeoapi configuration: a collection's ``view``.

``app.*`` is imported at the top of this module, nowhere else.
"""

import re

import pytest
from pygeoapi.config import load_schema
from pygeoapi.util import yaml_load

from app.pygeoapi.config_extensions import VIEW_SCHEMA, extend_schema, extension_problem
from app.pygeoapi.factory import ConfigValidationError, normalize_config

CONFIG_PATH = "tests/data/pygeoapi-config.yml"


@pytest.fixture
def config(monkeypatch) -> dict:
    """The suite's configuration, expanded the way the app expands it."""
    for name, value in {
        "HOST": "0.0.0.0",
        "PORT": "5000",
        "PYGEOAPI_BASEURL": "http://localhost:5000",
        "FASTGEOAPI_CONTEXT": "/geoapi",
    }.items():
        monkeypatch.setenv(name, value)
    with open(CONFIG_PATH) as handle:
        return yaml_load(handle)


def _collection_schemas(schema: dict) -> list[dict]:
    pattern = schema["properties"]["resources"]["patternProperties"]
    return [
        alternative
        for value in pattern.values()
        for alternative in value.get("anyOf", [value])
        if "extents" in alternative.get("properties", {})
    ]


def test_a_collection_with_a_view_is_accepted(config):
    config["resources"]["obs"]["view"] = {"center": [12.5, 42.0], "zoom": 6}

    normalized = normalize_config(config)

    assert normalized["resources"]["obs"]["view"] == {"center": [12.5, 42.0], "zoom": 6}


@pytest.mark.parametrize(
    ("view", "where"),
    [
        ({"center": [12.5, 42.0]}, "resources.obs.view"),
        ({"center": [200, 0], "zoom": 3}, "resources.obs.view.center.0"),
        ({"center": [0, 95], "zoom": 3}, "resources.obs.view.center.1"),
        ({"center": [0, 0], "zoom": 25}, "resources.obs.view.zoom"),
        ({"center": [0, 0], "zoom": 3, "pitch": 20}, "resources.obs.view"),
        ([12.5, 42.0, 6], "resources.obs.view"),
    ],
    ids=["no zoom", "longitude", "latitude", "zoom", "unknown key", "not an object"],
)
def test_a_wrong_view_is_refused_with_its_path(config, view, where):
    config["resources"]["obs"]["view"] = view

    with pytest.raises(ConfigValidationError, match=re.escape(f"configuration at {where}:")):
        normalize_config(config)


def test_resources_without_collections_pass():
    assert extension_problem({}) is None
    assert extension_problem({"resources": None}) is None
    assert extension_problem({"resources": {"hello": {"type": "process", "view": 1}}}) is None


def test_the_schema_offers_the_view_to_collections_only():
    schema = load_schema()

    extended = extend_schema(schema)

    assert all(alt["properties"]["view"] == VIEW_SCHEMA for alt in _collection_schemas(extended))
    assert all("view" not in alt["properties"] for alt in _collection_schemas(schema))
    processes = [
        alternative
        for value in extended["properties"]["resources"]["patternProperties"].values()
        for alternative in value.get("anyOf", [value])
        if "processor" in alternative.get("properties", {})
    ]
    assert processes and all("view" not in alt["properties"] for alt in processes)
