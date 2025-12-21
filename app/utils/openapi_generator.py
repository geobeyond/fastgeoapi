"""OpenAPI file generation utilities."""

import os
from pathlib import Path

from loguru import logger
from pygeoapi.openapi import generate_openapi_document

from app.config.app import configuration as cfg
from app.utils.pygeoapi_exceptions import PygeoapiEnvError


def ensure_openapi_file_exists() -> Path:
    """Ensure the OpenAPI file exists, generating it if necessary.

    This function checks if the pygeoapi OpenAPI file exists and generates
    it from the pygeoapi configuration if it doesn't.

    Returns
    -------
        Path to the OpenAPI file.

    Raises
    ------
        PygeoapiEnvError: If pygeoapi environment variables are not configured.
        FileNotFoundError: If the pygeoapi config file doesn't exist.
    """
    # Set required environment variables
    os.environ["PYGEOAPI_CONFIG"] = cfg.PYGEOAPI_CONFIG
    os.environ["PYGEOAPI_OPENAPI"] = cfg.PYGEOAPI_OPENAPI
    os.environ["HOST"] = cfg.HOST
    os.environ["PORT"] = cfg.PORT
    os.environ["PYGEOAPI_BASEURL"] = cfg.PYGEOAPI_BASEURL
    os.environ["FASTGEOAPI_CONTEXT"] = cfg.FASTGEOAPI_CONTEXT

    if not (os.environ["PYGEOAPI_CONFIG"] and os.environ["PYGEOAPI_OPENAPI"]):
        logger.error("pygeoapi variables are not configured")
        raise PygeoapiEnvError("PYGEOAPI_CONFIG and PYGEOAPI_OPENAPI are not set")

    pygeoapi_conf = Path.cwd() / os.environ["PYGEOAPI_CONFIG"]
    pygeoapi_oapi = Path.cwd() / os.environ["PYGEOAPI_OPENAPI"]

    if not pygeoapi_oapi.exists():
        logger.info(f"Generating OpenAPI file: {pygeoapi_oapi}")
        pygeoapi_oapi.write_text(data="")
        with pygeoapi_oapi.open(mode="w") as oapi_file:
            oapi_content = generate_openapi_document(
                pygeoapi_conf,
                output_format="yaml",
            )
            logger.debug(f"OpenAPI content: \n{oapi_content}")
            oapi_file.write(oapi_content)
        logger.info("OpenAPI file generated successfully")
    else:
        logger.debug(f"OpenAPI file already exists: {pygeoapi_oapi}")

    return pygeoapi_oapi
