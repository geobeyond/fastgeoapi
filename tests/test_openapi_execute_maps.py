"""``type_execute_request_maps`` on documents shaped like a resolved one.

After the remote references are resolved, the execute request schema is
either inlined in the operation or left in ``components`` behind a local
``$ref``. The OGC ``execute.yaml`` gives ``inputs`` and ``outputs`` no
``type``; both must come out as objects, and nothing else may change.
"""

from openapi_pydantic.v3.v3_0 import OpenAPI

from app.pygeoapi.openapi import type_execute_request_maps

EXECUTION = "/processes/hello-world/execution"
A_MAP = {"additionalProperties": {"type": "string"}}


def _document(path: str, schema: dict, **schemas: dict) -> dict:
    body = {"content": {"application/json": {"schema": schema}}}
    return {
        "openapi": "3.0.2",
        "info": {"title": "test", "version": "1"},
        "paths": {
            path: {"post": {"requestBody": body, "responses": {"200": {"description": "ok"}}}}
        },
        "components": {"schemas": schemas},
    }


def _apply(doc: dict) -> dict:
    openapi = type_execute_request_maps(OpenAPI.model_validate(doc))
    return openapi.model_dump(mode="json", by_alias=True, exclude_unset=True)


def _properties(doc: dict, path: str = EXECUTION) -> dict:
    body = doc["paths"][path]["post"]["requestBody"]
    return body["content"]["application/json"]["schema"]["properties"]


def test_inlined_maps_become_objects():
    schema = {"type": "object", "properties": {"inputs": dict(A_MAP), "outputs": dict(A_MAP)}}

    properties = _properties(_apply(_document(EXECUTION, schema)))

    assert properties["inputs"]["type"] == "object"
    assert properties["outputs"]["type"] == "object"


def test_a_schema_left_in_components_is_followed():
    execute = {"type": "object", "properties": {"inputs": dict(A_MAP)}}
    doc = _apply(_document(EXECUTION, {"$ref": "#/components/schemas/execute"}, execute=execute))

    assert doc["components"]["schemas"]["execute"]["properties"]["inputs"]["type"] == "object"


def test_a_declared_type_is_kept():
    schema = {"properties": {"inputs": {"type": "array", "items": {}}}}

    properties = _properties(_apply(_document(EXECUTION, schema)))

    assert properties["inputs"]["type"] == "array"


def test_operations_other_than_execution_are_untouched():
    path = "/collections/lakes/items"
    schema = {"properties": {"inputs": dict(A_MAP)}}

    properties = _properties(_apply(_document(path, schema)), path)

    assert "type" not in properties["inputs"]
