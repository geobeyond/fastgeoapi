"""Override vanilla openapi module."""

import yaml
from openapi_pydantic.v3.v3_0 import OpenAPI, SecurityScheme
from pydantic_core import ValidationError
from pygeoapi.openapi import generate_openapi_document as _upstream_generate_openapi_document

from app.auth.models import unauthorized
from app.config.app import configuration as cfg
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
