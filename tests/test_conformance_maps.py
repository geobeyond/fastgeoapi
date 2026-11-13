"""A provider says which conformance classes it meets, and the validator agrees."""

import pytest

from tests.maps_fixtures import map_provider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config

MAPS = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf"


@pytest.fixture(scope="module")
def served(tmp_path_factory):
    from starlette.testclient import TestClient

    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    archive = write_archive(
        tmp_path_factory.mktemp("conformance-maps") / "roads.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
    )
    config = _config({"roads": _collection("Roads", [map_provider(archive)])})
    document = build_openapi(config)
    declaration = (
        TestClient(build_pygeoapi_subapp(config, document))
        .get("/conformance", params={"f": "json"})
        .json()
    )
    return document, declaration


def test_the_map_provider_declares_its_classes(served):
    _, declaration = served

    assert {f"{MAPS}/core", f"{MAPS}/scaling", f"{MAPS}/spatial-subsetting"} <= set(
        declaration["conformsTo"]
    )
    assert f"{MAPS}/crs" not in declaration["conformsTo"]


def test_the_validator_finds_every_declared_class_described(served):
    from ogcapi_registry import parse_conformance_classes, validate_ogc_api

    document, declaration = served
    result = validate_ogc_api(document, parse_conformance_classes(declaration))
    critical = [
        finding.get("message")
        for finding in (getattr(result, "errors", None) or [])
        if finding.get("severity") == "critical"
    ]

    assert critical == []


def test_a_short_pygeoapi_name_is_not_imported():
    from app.pygeoapi.plugin import resolve_provider_class

    assert resolve_provider_class("GeoJSON") is None
    assert resolve_provider_class("app.provider.maplibre.MapLibreMapProvider").__name__ == (
        "MapLibreMapProvider"
    )
