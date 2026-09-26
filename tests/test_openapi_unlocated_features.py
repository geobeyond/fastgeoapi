"""``allow_unlocated_features`` on documents shaped like a resolved one.

The OGC ``featureGeoJSON.yaml`` requires a non-null ``geometry``, while
RFC 7946 section 3.2 allows ``null`` for a feature that has no location.
pygeoapi returns ``null`` when a request asks for ``skipGeometry=true``.
FastMCP turns ``nullable: true`` next to ``allOf`` into ``anyOf`` with
``null`` and drops it next to a bare ``$ref``, so the geometry becomes
``allOf: [$ref]`` plus ``nullable: true``.
"""

from openapi_pydantic.v3.v3_0 import OpenAPI

from app.pygeoapi.openapi import allow_unlocated_features, fix_resolved_document

GEOMETRY = {"$ref": "#/components/schemas/ogcapi-features-1__geometryGeoJSON"}


def _feature(geometry: dict) -> dict:
    return {
        "type": "object",
        "required": ["type", "geometry", "properties"],
        "properties": {
            "type": {"type": "string", "enum": ["Feature"]},
            "geometry": geometry,
            "properties": {"type": "object", "nullable": True},
        },
    }


def _document(**schemas: dict) -> dict:
    return {
        "openapi": "3.0.2",
        "info": {"title": "test", "version": "1"},
        "paths": {},
        "components": {"schemas": schemas},
    }


def _apply(doc: dict) -> dict:
    openapi = allow_unlocated_features(OpenAPI.model_validate(doc))
    return openapi.model_dump(mode="json", by_alias=True, exclude_unset=True)


def test_the_feature_geometry_accepts_null():
    doc = _apply(_document(feature=_feature(dict(GEOMETRY))))

    geometry = doc["components"]["schemas"]["feature"]["properties"]["geometry"]

    assert geometry == {"allOf": [GEOMETRY], "nullable": True}


def test_running_twice_wraps_once():
    doc = _apply(_apply(_document(feature=_feature(dict(GEOMETRY)))))

    assert doc["components"]["schemas"]["feature"]["properties"]["geometry"] == {
        "allOf": [GEOMETRY],
        "nullable": True,
    }


def test_a_schema_that_is_not_a_feature_is_untouched():
    other = _feature(dict(GEOMETRY))
    other["properties"]["type"]["enum"] = ["FeatureCollection"]

    doc = _apply(_document(other=other))

    assert doc["components"]["schemas"]["other"]["properties"]["geometry"] == GEOMETRY


def test_the_document_round_trip_changes_nothing_else():
    """``fix_resolved_document`` dumps with ``exclude_unset``: no defaults appear."""
    doc = _document(feature=_feature(dict(GEOMETRY)))
    doc["paths"] = {"/": {"get": {"responses": {"200": {"description": "ok"}}}}}

    fixed = fix_resolved_document(doc)

    assert fixed["paths"] == doc["paths"]
    assert "deprecated" not in fixed["paths"]["/"]["get"]
