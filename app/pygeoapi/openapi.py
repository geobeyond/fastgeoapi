"""Override vanilla openapi module."""

from openapi_pydantic.v3.v3_0 import OpenAPI, SecurityScheme
from pydantic_core import ValidationError

from app.auth.models import unauthorized
from app.config.app import configuration as cfg
from app.config.logging import create_logger
from app.pygeoapi.models import not_found

logger = create_logger("app.pygeoapi.openapi")


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
