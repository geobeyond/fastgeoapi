"""Override vanilla openapi module."""

import json
from typing import List

from openapi_pydantic.v3.v3_0 import OpenAPI
from openapi_pydantic.v3.v3_0 import SecurityScheme
from pydantic_core import ValidationError

from app.auth.models import unauthorized
from app.config.app import configuration as cfg
from app.config.logging import create_logger
from app.pygeoapi.models import not_found

logger = create_logger("app.pygeoapi.openapi")


def remove_external_refs(schema_dict):
    """Remove external HTTP/HTTPS $refs, keeping internal refs intact.

    This function removes external references (e.g., to schemas.opengis.net) and
    replaces them with simple placeholder schemas. This prevents network calls
    that would hang during schema resolution.

    Args:
        schema_dict: The OpenAPI schema as a dictionary

    Returns:
        Schema dict with external refs removed, internal refs preserved
    """

    def process(obj, path=""):
        """Recursively remove only external refs."""
        if isinstance(obj, dict):
            # Check if this is a pure $ref object
            if "$ref" in obj and len(obj) == 1:
                ref_value = obj["$ref"]
                if ref_value.startswith(("http://", "https://")):
                    # External ref - replace with context-appropriate placeholder
                    logger.debug(
                        f"Removing external ref at {path}: {ref_value[:60]}..."
                    )

                    # Determine what kind of placeholder to use based on path context
                    if "/parameters" in path or ".parameters" in path:
                        # Parameter reference - needs name field
                        return {
                            "name": "removed_param",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                            "description": "External parameter reference removed",
                        }
                    elif "/responses" in path or ".responses." in path:
                        # Response reference
                        return {
                            "description": "External response reference removed",
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            },
                        }
                    else:
                        # Schema or other reference
                        return {
                            "type": "object",
                            "description": "External reference removed",
                        }
                else:
                    # Internal ref - keep as-is
                    return obj
            else:
                # Regular dict - recurse into it
                return {
                    key: process(value, f"{path}.{key}") for key, value in obj.items()
                }
        elif isinstance(obj, list):
            return [process(item, f"{path}[{i}]") for i, item in enumerate(obj)]
        else:
            return obj

    return process(schema_dict)


def augment_security(doc: str, security_schemes: List[SecurityScheme]) -> OpenAPI:
    """Augment openapi document with security sections.

    Removes external $ref URLs that would cause Schemathesis to hang during
    network fetches. Internal refs are kept for native handling.
    """
    logger.info("Processing OpenAPI schema...")
    doc_dict = json.loads(doc)

    # Remove external refs only (prevents hanging on network calls)
    logger.debug("Removing external references...")
    resolved_doc = remove_external_refs(doc_dict)
    logger.info("External references removed successfully")

    # Now validate and process the resolved schema
    try:
        openapi = OpenAPI.model_validate(resolved_doc)
    except ValidationError as e:
        logger.error(e)
        raise
    security_scheme_types = [
        security_scheme.type for security_scheme in security_schemes
    ]
    _security_schemes = {"securitySchemes": {}}  # type: dict[str, dict]
    if all(
        item in ["http", "apiKey", "oauth2", "openIdConnect"]
        for item in security_scheme_types
    ):
        dumped_schemes = {}
        for scheme in security_schemes:
            dumped_schemes.update(
                {
                    f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": scheme.model_dump(  # noqa B950
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
    paths = openapi.paths
    secured_paths = {}
    if paths:
        for key, value in paths.items():
            if "openapi" not in key:
                if value.get:
                    value.get.security = [
                        {f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": []}
                    ]
                    if value.get.responses:
                        value.get.responses.update(unauthorized)
                if value.post:
                    value.post.security = [
                        {f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": []}
                    ]
                    if value.post.responses:
                        value.post.responses.update(unauthorized)
                if value.options:
                    value.options.security = [
                        {f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": []}
                    ]
                    if value.options.responses:
                        value.options.responses.update(unauthorized)
                        # Remove when it is fixed from pygeoapi
                        value.options.responses.update(not_found)
                if value.delete:
                    value.delete.security = [
                        {f"pygeoapi {cfg.PYGEOAPI_SECURITY_SCHEME}": []}
                    ]
                    if value.delete.responses:
                        value.delete.responses.update(unauthorized)
                secured_paths.update({key: value})

    if secured_paths:
        content["paths"] = secured_paths
    return OpenAPI(**content)
