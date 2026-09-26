"""Override vanilla openapi module."""

import importlib

import yaml
from openapi_pydantic.v3.v3_0 import (
    DataType,
    OpenAPI,
    Reference,
    RequestBody,
    Schema,
    SecurityScheme,
)
from pydantic_core import ValidationError
from pygeoapi.openapi import generate_openapi_document as _upstream_generate_openapi_document

from app.auth.models import unauthorized
from app.config.logging import create_logger
from app.pygeoapi.models import not_found

logger = create_logger("app.pygeoapi.openapi")


def describe_servers(content: dict) -> None:
    """State each server's audience and environment in the document.

    pygeoapi emits a bare ``url`` plus a generic description, which leaves
    a consumer guessing whether they are looking at a staging box or the
    real thing — and raises OWASP API9:2023 (improper inventory
    management) on both counts.

    ``x-internal`` is set to ``False`` because the surface pygeoapi serves
    is meant for external consumers; an operator running it behind a
    perimeter can override it. The environment is taken from
    ``ENV_STATE`` rather than guessed from the URL, so it says what the
    deployment was configured to be.
    """
    # Imported here rather than at module level. Building fastgeoapi's
    # settings demands a configured fastgeoapi, and this module is
    # reached — through the factory — by `fastgeoapi config edit`, which
    # is meant to work for someone who has only pygeoapi and a document
    # to fix. Nothing the editor calls needs these values; an import at
    # the top would have demanded them all the same.
    from app.config.app import configuration as cfg

    servers = content.get("servers")
    if not servers:
        return
    environment = "production" if str(cfg.ENV_STATE).lower().startswith("prod") else "local"
    for server in servers:
        server.setdefault("x-internal", False)
        description = server.get("description") or "pygeoapi"
        if environment not in description:
            server["description"] = f"{description} — {environment} environment"


def describe_jwt_validation(content: dict) -> None:
    """Describe what JWT validation actually enforces.

    OWASP API2:2023 asks a scheme declaring ``bearerFormat: JWT`` to say
    what it does about RFC 8725. The tempting move is to write "supports
    RFC 8725" and satisfy the linter, but our conformance is conditional:
    issuer and audience are only checked when configured, and one IdP
    (Cognito) gets its audience back-filled from ``client_id``. Declaring
    flat support would be the same dishonesty as a check that cannot
    fail — a reader would take it as a guarantee.

    So this states the part that always holds (the algorithm comes from
    the provider's key set, never from the token header, which is the
    RFC 8725 §3.1 defence against algorithm confusion) and marks the rest
    as conditional.
    """
    schemes = (content.get("components") or {}).get("securitySchemes") or {}
    for scheme in schemes.values():
        if not isinstance(scheme, dict) or scheme.get("bearerFormat") != "JWT":
            continue
        scheme.setdefault(
            "description",
            "Bearer JWT verified against the identity provider's published JWKS. "
            "The signing algorithm is taken from that key set and never from the "
            "token header, which is the RFC8725 section 3.1 defence against "
            "algorithm confusion. Issuer and audience are enforced as essential "
            "claims when OAUTH2_EXPECTED_ISSUER and OAUTH2_EXPECTED_AUDIENCE are "
            "configured; without them those claims are not checked.",
        )


def augment_security(doc: str, security_schemes: list[SecurityScheme]) -> OpenAPI:
    """Augment openapi document with security sections."""
    # Imported here rather than at module level. Building fastgeoapi's
    # settings demands a configured fastgeoapi, and this module is
    # reached — through the factory — by `fastgeoapi config edit`, which
    # is meant to work for someone who has only pygeoapi and a document
    # to fix. Nothing the editor calls needs these values; an import at
    # the top would have demanded them all the same.
    from app.config.app import configuration as cfg

    try:
        openapi = OpenAPI.model_validate_json(doc)
    except ValidationError as e:
        logger.error(e)
        raise
    security_scheme_types = [security_scheme.type for security_scheme in security_schemes]
    _security_schemes = {"securitySchemes": {}}  # type: dict[str, dict]
    if all(item in ["http", "apiKey", "oauth2", "openIdConnect"] for item in security_scheme_types):
        dumped_schemes = {}
        for scheme in security_schemes:
            dumped_schemes.update(
                {
                    f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": scheme.model_dump(
                        by_alias=True, exclude_none=True
                    )
                }
            )
        _security_schemes["securitySchemes"] = dumped_schemes
    content = openapi.model_dump(by_alias=True, exclude_none=True)
    components = content.get("components")
    if components:
        components.update(_security_schemes)
    content["components"] = components
    # The served spec must be as honest as the one handed to fastmcp:
    # correct pygeoapi's queryables wrapper here too (Bug 3b).
    fix_queryables_response_schema(content)
    describe_servers(content)
    describe_jwt_validation(content)
    paths = openapi.paths
    secured_paths = {}
    if paths:
        for key, value in paths.items():
            if "openapi" not in key:
                if value.get:
                    value.get.security = [{f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": []}]
                    if value.get.responses:
                        value.get.responses.update(unauthorized)
                if value.post:
                    value.post.security = [{f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": []}]
                    if value.post.responses:
                        value.post.responses.update(unauthorized)
                if value.options:
                    value.options.security = [{f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": []}]
                    if value.options.responses:
                        value.options.responses.update(unauthorized)
                        # Remove when it is fixed from pygeoapi
                        value.options.responses.update(not_found)
                if value.delete:
                    value.delete.security = [{f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": []}]
                    if value.delete.responses:
                        value.delete.responses.update(unauthorized)
                secured_paths.update({key: value})

    if secured_paths:
        content["paths"] = secured_paths
    return OpenAPI(**content)


def fix_queryables_response_schema(doc: dict) -> dict:
    """Replace pygeoapi's queryables wrapper schema with the real shape.

    Upstream declares ``components.schemas.queryables`` as a wrapper
    object with a required ``queryables`` array
    (``pygeoapi/openapi.py:440-451``, still present in 0.24), but the
    handlers behind ``/collections/{id}/queryables`` (Features Part 3)
    and ``/collections/{id}/schema`` (which reuses the same response
    component) actually return a bare JSON Schema document. Consumers
    that validate responses against the spec — fastmcp's output
    validation on the generated MCP tools — reject every legitimate
    200 with "Output validation error: 'queryables' is a required
    property" (vault: Bug 3b). Rewrite the component to the truthful,
    permissive shape. Remove once fixed upstream in pygeoapi.
    """
    schemas = doc.get("components", {}).get("schemas", {})
    if "queryables" in schemas:
        schemas["queryables"] = {
            "type": "object",
            "description": (
                "A JSON Schema document describing the queryable/"
                "returnable properties of the collection "
                "(OGC API - Features Part 3 / Part 5)."
            ),
            "properties": {
                "$schema": {"type": "string"},
                "$id": {"type": "string"},
                "type": {"type": "string"},
                "title": {"type": "string"},
                "properties": {"type": "object"},
            },
            "additionalProperties": True,
        }
    return doc


def fix_conformance_and_collections_responses(doc: dict) -> dict:
    """Point /conformance and /collections at their own Part 1 responses.

    pygeoapi references ``responses/LandingPage`` of OGC API - Features
    Part 1 for the landing page, the conformance declaration and the list
    of collections (``pygeoapi/openapi.py:298,347,365``, still in 0.24).
    The landing page schema requires ``links``, and a conformance
    declaration carries only ``conformsTo``, so a client that validates a
    response against the document rejects a correct answer. The MCP tools
    inherit the schema, and on the demo the Claude connector rejected every
    result of ``getConformanceDeclaration``. The same Part 1 document
    defines ``ConformanceDeclaration`` and ``Collections``, so only the
    fragment of the reference changes. Remove once fixed upstream in
    pygeoapi.
    """
    own_response = {"/conformance": "ConformanceDeclaration", "/collections": "Collections"}
    paths = doc.get("paths", {})
    for path, name in own_response.items():
        response = paths.get(path, {}).get("get", {}).get("responses", {}).get("200")
        reference = response.get("$ref", "") if isinstance(response, dict) else ""
        if reference.endswith("#/components/responses/LandingPage"):
            response["$ref"] = f"{reference.split('#')[0]}#/components/responses/{name}"
    return doc


def _dereference(openapi: OpenAPI, node):
    """Follow a local ``#/components/...`` reference, or return the node as it is."""
    while isinstance(node, Reference) and node.ref.startswith("#/components/"):
        _, _, section, name = node.ref.split("/", 3)
        entries = getattr(openapi.components, section, None) or {}
        node = entries.get(name.replace("~1", "/").replace("~0", "~"))
    return node


def type_execute_request_maps(openapi: OpenAPI) -> OpenAPI:
    """Declare ``inputs`` and ``outputs`` of an execute request as objects.

    The OGC API - Processes ``execute.yaml`` describes both as maps,
    through ``additionalProperties``, and gives them no ``type``. A JSON
    Schema reader may then accept any value for them, and on the demo the
    Claude connector sent ``inputs`` as a JSON string: pygeoapi answered
    400 ``'str' object has no attribute 'get'``. This runs on the
    document after its remote references are resolved, because before
    that the request body is a single ``$ref`` to the OGC file. A
    property changes only when it has ``additionalProperties`` or
    ``properties`` and no ``type``. Remove once the OGC schema declares
    the type.
    """
    for path, item in (openapi.paths or {}).items():
        if not path.endswith("/execution") or item.post is None:
            continue
        body = _dereference(openapi, item.post.requestBody)
        if not isinstance(body, RequestBody):
            continue
        media = body.content.get("application/json")
        schema = _dereference(openapi, media.media_type_schema if media else None)
        if not isinstance(schema, Schema) or not schema.properties:
            continue
        for name in ("inputs", "outputs"):
            prop = _dereference(openapi, schema.properties.get(name))
            if (
                isinstance(prop, Schema)
                and prop.type is None
                and (prop.additionalProperties is not None or prop.properties)
            ):
                prop.type = DataType.OBJECT
    return openapi


def allow_unlocated_features(openapi: OpenAPI) -> OpenAPI:
    """Let the geometry of a GeoJSON feature be ``null``.

    The OGC ``featureGeoJSON.yaml`` of Features Part 1 requires a
    ``geometry``, while RFC 7946 section 3.2 allows ``null`` for a feature
    that has no location. pygeoapi returns ``null`` when a request asks
    for ``skipGeometry=true``, and on the demo the Claude connector
    rejected those results against the tool's output schema. FastMCP
    turns ``nullable: true`` next to ``allOf`` into ``anyOf`` with
    ``null`` and drops it next to a bare ``$ref``, so a referenced
    geometry becomes ``allOf: [$ref]`` plus ``nullable: true``.

    The function looks only at ``components.schemas``. The resolver
    moves the schemas of the remote OGC documents there, and in the
    resolved document the feature schema is
    ``ogcapi-features-1__featureGeoJSON``. The call with
    ``skipGeometry=true`` in ``tests/test_mcp_tool_schemas.py`` fails if
    that stops being true. Remove once the OGC schema allows a null
    geometry.
    """
    schemas = openapi.components.schemas if openapi.components else None
    for schema in (schemas or {}).values():
        if not isinstance(schema, Schema) or not schema.properties:
            continue
        kind = schema.properties.get("type")
        if not (isinstance(kind, Schema) and kind.enum == ["Feature"]):
            continue
        geometry = schema.properties.get("geometry")
        if isinstance(geometry, Reference):
            schema.properties["geometry"] = Schema(allOf=[geometry], nullable=True)
        elif isinstance(geometry, Schema):
            geometry.nullable = True
    return openapi


def fix_resolved_document(doc: dict) -> dict:
    """Apply the corrections that need the remote references resolved.

    Every MCP server built from our document (runtime, reload, editor
    preview) calls this on the output of ``resolve_external_refs``, so the
    three agree on the tool schemas. The document goes through the
    openapi-pydantic model once: validated, corrected, then dumped with
    ``exclude_unset`` so that nothing the corrections did not touch
    changes, defaults included.
    """
    openapi = OpenAPI.model_validate(doc)
    type_execute_request_maps(openapi)
    allow_unlocated_features(openapi)
    return openapi.model_dump(mode="json", by_alias=True, exclude_unset=True)


#: Provider classes whose ``query`` applies the CQL2 filter it receives
#: as ``filterq``, checked against pygeoapi 0.24. The other bundled
#: providers accept the argument and ignore it.
CQL2_FILTERING_PROVIDERS = frozenset(
    {
        "pygeoapi.provider.sql.GenericSQLProvider",
        "pygeoapi.provider.sql.PostgreSQLProvider",
        "pygeoapi.provider.sql.MySQLProvider",
        "pygeoapi.provider.elasticsearch_.ElasticsearchProvider",
        "pygeoapi.provider.elasticsearch_.ElasticsearchCatalogueProvider",
        "pygeoapi.provider.opensearch_.OpenSearchProvider",
        "pygeoapi.provider.opensearch_.OpenSearchCatalogueProvider",
        "pygeoapi.provider.oracle.OracleProvider",
        "app.provider.geoparquet.GeoParquetProvider",
    }
)


def _provider_filters_cql2(name: str) -> bool:
    """Say whether the configured provider applies a CQL2 filter.

    The name is resolved the way pygeoapi's ``load_plugin`` does: a short
    name through the plugin registry, anything else as a dotted path. A
    class that is not in ``CQL2_FILTERING_PROVIDERS`` still counts when
    one of its bases is, so a subclass of the SQL provider keeps the
    operation. The known classes are matched by name, without importing
    their modules and the database drivers they need.
    """
    from pygeoapi.plugin import PLUGINS

    dotted = PLUGINS["provider"].get(name, name)
    if dotted in CQL2_FILTERING_PROVIDERS:
        return True
    module_name, _, class_name = dotted.rpartition(".")
    if not module_name:
        return False
    try:
        cls = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError):
        return False
    return any(
        f"{base.__module__}.{base.__qualname__}" in CQL2_FILTERING_PROVIDERS
        for base in getattr(cls, "__mro__", ())
    )


def _items_provider(resource: dict) -> dict | None:
    """The provider pygeoapi uses for the items of a collection.

    ``get_oas_30`` takes the first ``record`` provider when there is one,
    otherwise the first ``feature`` provider.
    """
    providers = resource.get("providers") or []
    for provider_type in ("record", "feature"):
        for provider in providers:
            if isinstance(provider, dict) and provider.get("type") == provider_type:
                return provider
    return None


def drop_unfiltered_cql2_operations(doc: dict, config: dict) -> dict:
    """Describe the CQL2 operation only where the provider filters.

    pygeoapi writes ``POST /collections/{id}/items`` with a CQL2 JSON body
    for every feature and record collection (``api/itemtypes.py``, 0.24).
    Providers that do not use ``filterq``, CSV and GeoJSON among them,
    answer that request with the whole collection, and an MCP agent that
    calls the generated tool takes the result as filtered. This removes
    the operation for those collections. An editable provider keeps it,
    because the same ``POST`` adds a feature. Remove once pygeoapi writes
    the operation according to what the provider supports.
    """
    paths = doc.get("paths", {})
    for name, resource in (config.get("resources") or {}).items():
        if not isinstance(resource, dict) or resource.get("type") != "collection":
            continue
        item = paths.get(f"/collections/{name}/items")
        if not isinstance(item, dict) or "post" not in item:
            continue
        provider = _items_provider(resource)
        if provider is None or provider.get("editable", False):
            continue
        if not _provider_filters_cql2(str(provider.get("name", ""))):
            del item["post"]
    return doc


def describe_tilesets(doc: dict) -> dict:
    """Write in the tileset description the server already answers.

    `GET /collections/{collectionId}/tiles/{tileMatrixSetId}` is the
    tileset resource. pygeoapi routes it (`starlette_app.py:195-203`) and
    answers it — measured against the demo on 2026-09-16, 200 with the
    tileset document — while `api/tiles.py` writes only the list at
    `…/tiles` (line 471) and the tile data path (line 499). Nothing in
    between, for any collection.

    OGC API - Tiles states it with the verb it reserves for requirements:
    `/req/tileset/description`, "the tileset endpoint SHALL support
    negotiation of an application/json response". So the document
    understates a server that conforms, and since the MCP tools are
    generated from the document, an agent has no way to describe a
    tileset it can already fetch tiles from.

    The operation is built from the list beside it rather than written
    from scratch: same tags, same error responses, same parameter
    references, so the addition reads like the rest of the document
    instead of like a patch. Remove once fixed upstream in pygeoapi.
    """
    from pygeoapi.openapi import OPENAPI_YAML

    tiles_openapi = OPENAPI_YAML["oapit"]
    tile_set_response = f"{tiles_openapi.rsplit('/', 1)[0]}/responses/tiles-core/rTileSet.yaml"

    paths = doc.get("paths", {})
    for path in list(paths):
        if not path.endswith("/tiles"):
            continue
        target = f"{path}/{{tileMatrixSetId}}"
        listing = paths[path].get("get")
        if target in paths or not listing:
            continue

        responses = dict(listing.get("responses", {}))
        responses["200"] = {"$ref": tile_set_response}

        operation_id = listing.get("operationId", "")
        paths[target] = {
            "get": {
                "tags": list(listing.get("tags", [])),
                "summary": "Describe a tileset of this collection",
                "description": listing.get("description", ""),
                "operationId": operation_id.replace("getTileSetsList", "getTileSet"),
                "parameters": [
                    {"$ref": f"{tiles_openapi}#/components/parameters/tileMatrixSetId"},
                    *listing.get("parameters", []),
                ],
                "responses": responses,
            }
        }
    return doc


def drop_unused_tags(doc: dict) -> dict:
    """Declare only the tags the document's own operations use.

    Each pygeoapi API module returns a module-level tag object whether or
    not it contributes a path, and the guard meant to drop them
    (``pygeoapi/openapi.py:556``, 0.24) reads ``if not sub_tags and not
    sub_paths`` — a conjunction over a list literal that is never empty,
    so it never fires. Those module tags then go unused even when their
    spec group is active, because operations are tagged with the id of
    the collection or process they serve: on the demo, ``tiles`` and
    ``features`` had no operation while tile and feature collections were
    being served. Measured there on 2026-09-15: fifteen declared tags,
    eight of them with no operation and no description.

    An unused tag is not invalid, it is noise that spreads: a renderer
    draws an empty section for each, and a generator makes an empty group.
    Which is why the rule here is not the registry's — ``active_specs``
    answers what the configuration mounts, and would keep ``tiles``
    anyway — but the document's own: a tag survives if an operation
    claims it. Remove once fixed upstream in pygeoapi.
    """
    if not doc.get("tags"):
        return doc
    used = {
        tag
        for item in doc.get("paths", {}).values()
        for operation in item.values()
        # A path item also holds `parameters`, `servers`, `summary` and
        # may hold a `$ref`: only the operations carry tags.
        if isinstance(operation, dict)
        for tag in operation.get("tags", [])
    }
    doc["tags"] = [tag for tag in doc["tags"] if tag.get("name") in used]
    return doc


def generate_openapi_document(cfg_file, output_format="yaml"):
    """Generate the pygeoapi OpenAPI document with fastgeoapi corrections.

    Delegates to upstream ``pygeoapi.openapi.generate_openapi_document``
    and applies the document-level fixes this package owns (currently
    ``fix_queryables_response_schema``, Bug 3b) so that EVERY consumer
    of the generated file — pygeoapi's own /openapi endpoint, the MCP
    tool generation, external readers — inherits the corrections at the
    source instead of patching at each consumption point.
    """
    raw = _upstream_generate_openapi_document(cfg_file, output_format=output_format)
    if output_format == "json":
        import json

        doc = json.loads(raw)
        fix_queryables_response_schema(doc)
        return json.dumps(doc, default=str)
    doc = yaml.safe_load(raw)
    fix_queryables_response_schema(doc)
    return yaml.safe_dump(doc, sort_keys=False)
