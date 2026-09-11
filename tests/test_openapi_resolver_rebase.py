"""Local `$ref`s inside inlined remote documents are relative to *that* document.

The resolver inlines remote content at the `$ref` site. Before this fix it
kept every `#/...` pointer found in that content untouched, so pointers
that were local to the remote document ended up aimed at our root, where
their targets do not exist: 489 dangling references on the demo
document (2026-09-10), 50 of them `#/$defs/*` from `cql2.json` and five
`#/components/schemas/*` from OGC fragments. The same resolved document
feeds FastMCP, so the CQL2 tools carried broken input schemas.

The fix hoists the remote targets into our `components`, under a name
prefixed by the remote document, and rewrites the pointers — the shape
FastMCP already turns into tool `$defs`. Recursive schemas (CQL2 is one)
stay recursive through the hoisted names instead of expanding forever.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import httpx2
import pytest
from fastmcp import FastMCP

# Bound as a module object on purpose: other test modules purge `app.*`
# from `sys.modules`, after which `mock.patch("app.utils.openapi_resolver…")`
# by name would patch a fresh re-import while the function called here
# still lives in this one — and would fetch the real OGC documents.
import app.utils.openapi_resolver as openapi_resolver


def _navigate(doc: Any, pointer: str) -> Any:
    """Follow a JSON pointer (without the leading '#'); None when it dangles."""
    current = doc
    for part in pointer.strip("/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _local_refs(obj: Any, acc: list[str] | None = None) -> list[str]:
    """Every local `$ref` value in the document, in traversal order."""
    acc = [] if acc is None else acc
    if isinstance(obj, dict):
        ref = obj.get("$ref")
        if isinstance(ref, str) and ref.startswith("#"):
            acc.append(ref)
        for value in obj.values():
            _local_refs(value, acc)
    elif isinstance(obj, list):
        for item in obj:
            _local_refs(item, acc)
    return acc


def _assert_nothing_dangles(doc: dict[str, Any]) -> None:
    dangling = sorted({ref for ref in _local_refs(doc) if _navigate(doc, ref[1:]) is None})
    assert dangling == [], f"dangling local references: {dangling}"


CQL2 = {
    # A slice of schemas.opengis.net/cql2/1.0/cql2.json: `$defs` with
    # document-local pointers, and a recursive definition. The root is a
    # `oneOf`, as in the real document — which is why FastMCP carries the
    # whole root along as the `body` parameter instead of flattening it.
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "oneOf": [{"$ref": "#/$defs/andOrExpression"}, {"$ref": "#/$defs/notExpression"}],
    "$defs": {
        "booleanExpression": {
            "oneOf": [
                {"$ref": "#/$defs/andOrExpression"},
                {"$ref": "#/$defs/notExpression"},
                {"type": "boolean"},
            ]
        },
        "andOrExpression": {
            "type": "object",
            "properties": {
                "op": {"enum": ["and", "or"]},
                "args": {"type": "array", "items": {"$ref": "#/$defs/booleanExpression"}},
            },
        },
        "notExpression": {
            "type": "object",
            "properties": {
                "op": {"const": "not"},
                "args": {"type": "array", "items": {"$ref": "#/$defs/booleanExpression"}},
            },
        },
    },
}

FEATURES = {
    # The shape of ogcapi-features-1.yaml: a response whose schema points
    # at the *remote* document's own components.
    "components": {
        "responses": {
            "Feature": {
                "description": "A feature.",
                "content": {
                    "application/geo+json": {
                        "schema": {"$ref": "#/components/schemas/featureGeoJSON"}
                    }
                },
            }
        },
        "schemas": {
            "featureGeoJSON": {
                "type": "object",
                "properties": {
                    "type": {"const": "Feature"},
                    "links": {"type": "array", "items": {"$ref": "#/components/schemas/link"}},
                },
            },
            # Same name as one of OUR schemas, different content: the two
            # must never be confused.
            "link": {"type": "object", "properties": {"href": {"type": "string"}}},
        },
    }
}


def _fetch(url: str) -> dict[str, Any]:
    if url.endswith("cql2.json"):
        return CQL2
    if url.endswith("ogcapi-features-1.yaml"):
        return FEATURES
    raise AssertionError(f"unexpected fetch: {url}")


def _resolve(spec: dict[str, Any]) -> dict[str, Any]:
    with mock.patch.object(openapi_resolver, "_fetch_remote_document", side_effect=_fetch):
        return openapi_resolver.resolve_external_refs(spec)


def test_a_whole_remote_document_with_defs_leaves_no_dangling_pointer():
    """`cql2.json` inlined whole: its `#/$defs/*` must not point at our root."""
    spec = {
        "openapi": "3.0.2",
        "paths": {
            "/collections/lakes/items": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "https://schemas.opengis.net/cql2/1.0/cql2.json"}
                            }
                        }
                    }
                }
            }
        },
    }

    resolved = _resolve(spec)

    _assert_nothing_dangles(resolved)
    assert not [ref for ref in _local_refs(resolved) if ref.startswith("#/$defs/")]


def test_remote_definitions_are_hoisted_into_our_components_under_a_prefixed_name():
    """The targets move into `components/schemas`, named after their document.

    That is the one place FastMCP knows how to turn into tool `$defs`, and
    the prefix keeps `link` from the OGC document apart from our `link`.
    """
    spec = {
        "openapi": "3.0.2",
        "components": {
            "schemas": {
                "link": {"type": "object", "properties": {"rel": {"type": "string"}}},
            }
        },
        "paths": {
            "/collections/lakes/items/{featureId}": {
                "get": {
                    "responses": {
                        "200": {
                            "$ref": "https://schemas.opengis.net/ogcapi/features/part1/1.0/openapi/ogcapi-features-1.yaml#/components/responses/Feature"
                        }
                    }
                }
            }
        },
    }

    resolved = _resolve(spec)

    _assert_nothing_dangles(resolved)
    response = resolved["paths"]["/collections/lakes/items/{featureId}"]["get"]["responses"]["200"]
    schema_ref = response["content"]["application/geo+json"]["schema"]["$ref"]
    assert schema_ref.startswith("#/components/schemas/"), schema_ref
    assert schema_ref != "#/components/schemas/featureGeoJSON", "must carry the document prefix"
    hoisted = _navigate(resolved, schema_ref[1:])
    assert hoisted["properties"]["type"] == {"const": "Feature"}
    # The OGC `link` is hoisted under a prefixed name; ours is untouched.
    ogc_link_ref = hoisted["properties"]["links"]["items"]["$ref"]
    assert ogc_link_ref != "#/components/schemas/link"
    assert _navigate(resolved, ogc_link_ref[1:]) == FEATURES["components"]["schemas"]["link"]
    assert resolved["components"]["schemas"]["link"] == spec["components"]["schemas"]["link"]


def test_recursive_remote_schemas_stay_recursive_instead_of_expanding():
    """CQL2's boolean expression refers to itself: the fix must not inline it forever."""
    spec = {
        "openapi": "3.0.2",
        "components": {
            "schemas": {"filter": {"$ref": "https://schemas.opengis.net/cql2/1.0/cql2.json"}}
        },
    }

    resolved = _resolve(spec)

    _assert_nothing_dangles(resolved)
    names = [n for n in resolved["components"]["schemas"] if n.endswith("booleanExpression")]
    assert len(names) == 1, names
    boolean_expression = resolved["components"]["schemas"][names[0]]
    # The recursion goes through the hoisted name, not through a copy.
    args_items = _navigate(resolved, f"/components/schemas/{names[0]}")["oneOf"][0]
    assert args_items["$ref"].startswith("#/components/schemas/")
    and_or = _navigate(resolved, args_items["$ref"][1:])
    assert and_or["properties"]["args"]["items"] == {"$ref": f"#/components/schemas/{names[0]}"}
    assert boolean_expression["oneOf"][2] == {"type": "boolean"}


CQL2_QUERY = {
    "openapi": "3.0.2",
    "info": {"title": "test", "version": "1"},
    "paths": {
        "/collections/lakes/items": {
            "post": {
                "operationId": "queryLakes",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "https://schemas.opengis.net/cql2/1.0/cql2.json"}
                        }
                    },
                },
                "responses": {"200": {"description": "ok"}},
            }
        }
    },
}


def test_an_inlined_whole_document_does_not_carry_its_dead_defs_along():
    """Once its targets are hoisted, the remote document's `$defs` block is dead weight.

    Worse than weight: the pointers inside it were rewritten to our
    components, and FastMCP does not descend into `$defs` — so on the demo
    document the CQL2 tool schema still carried 97 of them, all broken.
    """
    resolved = _resolve(CQL2_QUERY)

    body = resolved["paths"]["/collections/lakes/items"]["post"]["requestBody"]
    schema = body["content"]["application/json"]["schema"]
    assert "$defs" not in schema, sorted(schema)
    assert schema["oneOf"][0]["$ref"].startswith("#/components/schemas/cql2__")


@pytest.mark.asyncio
async def test_fastmcp_turns_the_hoisted_components_into_whole_tool_defs():
    """The end the fix serves: a tool schema in which every pointer resolves."""
    resolved = _resolve(CQL2_QUERY)
    server = FastMCP.from_openapi(
        openapi_spec=resolved,
        client=httpx2.AsyncClient(base_url="http://example.invalid"),
        name="test",
    )

    (tool,) = [t for t in await server.list_tools() if t.name == "queryLakes"]

    refs = _local_refs(tool.parameters)
    assert refs, "the tool schema lost its references altogether"
    assert not [ref for ref in refs if ref.startswith("#/components/")], refs
    _assert_nothing_dangles(tool.parameters)
    assert any(name.endswith("booleanExpression") for name in tool.parameters["$defs"])


def test_our_own_local_refs_are_still_left_alone():
    """Only pointers found inside remote content are rebased; ours are ours."""
    spec = {
        "openapi": "3.0.2",
        "components": {"schemas": {"Error": {"type": "object"}}},
        "paths": {
            "/": {
                "get": {
                    "responses": {
                        "400": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Error"}
                                }
                            }
                        }
                    }
                }
            }
        },
    }

    resolved = _resolve(spec)

    schema = resolved["paths"]["/"]["get"]["responses"]["400"]["content"]["application/json"][
        "schema"
    ]
    assert schema == {"$ref": "#/components/schemas/Error"}
    assert resolved["components"]["schemas"] == {"Error": {"type": "object"}}
