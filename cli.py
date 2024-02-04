"""Command-line interface."""
import os
from pathlib import Path

import typer
from app.config.app import configuration as cfg
from app.utils.pygeoapi_exceptions import PygeoapiEnvError
from app.utils.pygeoapi_exceptions import PygeoapiLanguageError
from loguru import logger
from openapi_pydantic.v3.v3_0_3 import OpenAPI
from openapi_pydantic.v3.v3_0_3 import SecurityScheme
from rich.console import Console

from pygeoapi.l10n import LocaleError
from pygeoapi.openapi import generate_openapi_document
from pygeoapi.provider.base import ProviderConnectionError


err_console = Console(stderr=True)

app = typer.Typer()


@app.callback()
def main_app_callback(ctx: typer.Context):
    """Commandline interface for fastgeoapi."""


@app.command(name="openapi")
def openapi(ctx: typer.Context) -> None:
    """Generate openapi document enriched with security schemes."""
    try:
        # override pygeoapi os variables
        os.environ["PYGEOAPI_CONFIG"] = cfg.PYGEOAPI_CONFIG
        os.environ["PYGEOAPI_OPENAPI"] = cfg.PYGEOAPI_OPENAPI
        os.environ["PYGEOAPI_BASEURL"] = cfg.PYGEOAPI_BASEURL
        if not (os.environ["PYGEOAPI_CONFIG"] and os.environ["PYGEOAPI_OPENAPI"]):
            logger.error("pygeoapi variables are not configured")
            raise PygeoapiEnvError("PYGEOAPI_CONFIG and PYGEOAPI_OPENAPI are not set")
        else:
            # fill pygeoapi configuration with fastapi host and port
            os.environ["HOST"] = cfg.HOST
            os.environ["PORT"] = cfg.PORT

            pygeoapi_conf = Path.cwd() / os.environ["PYGEOAPI_CONFIG"]
            pygeoapi_oapi = Path.cwd() / os.environ["PYGEOAPI_OPENAPI"]
            with pygeoapi_oapi.with_suffix(".json").open(mode="w") as oapi_file:
                oapi_content = generate_openapi_document(
                    pygeoapi_conf,
                    output_format="json",
                )
                logger.debug(f"OpenAPI content: \n{oapi_content}")
                security_scheme = None
                if cfg.OPA_ENABLED:
                    if cfg.API_KEY_ENABLED:
                        raise ValueError(
                            "OPA_ENABLED and API_KEY_ENABLED are mutually exclusive"
                        )
                    security_scheme = SecurityScheme(
                        type="openIdConnect",
                        name="OIDC",
                        openIdConnectUrl=cfg.OIDC_WELL_KNOWN_ENDPOINT,
                    )
                elif cfg.API_KEY_ENABLED:
                    if cfg.OPA_ENABLED:
                        raise ValueError(
                            "OPA_ENABLED and API_KEY_ENABLED are mutually exclusive"
                        )
                    if not cfg.PYGEOAPI_KEY_GLOBAL:
                        raise ValueError("pygeoapi API KEY is missing")
                    os.environ["PYGEOAPI_KEY_GLOBAL"] = cfg.PYGEOAPI_KEY_GLOBAL
                    security_scheme = SecurityScheme(
                        type="apiKey", name="X-API-KEY", security_scheme_in="header"
                    )
                openapi = OpenAPI.model_validate_json(oapi_content)
                if security_scheme:
                    dict_openapi = openapi.model_dump(by_alias=True, exclude_none=True)
                    components = dict_openapi.get("components")
                    if components:
                        components.update(security_scheme)
                    paths = openapi.paths
                    if paths:
                        secured_paths = {}
                        for key, value in paths.items():
                            if value.get:
                                value.get.security = [{"PygeoApiKey": []}]
                            if value.post:
                                value.post.security = [{"PygeoApiKey": []}]
                            secured_paths.update({key: value})
                    if secured_paths:
                        dict_openapi["paths"] = secured_paths
                    enriched_openapi = OpenAPI(**dict_openapi)
                else:
                    enriched_openapi = openapi
                oapi_file.write(enriched_openapi.model_dump_json())

    except FileNotFoundError:
        logger.error("Please configure pygeoapi settings in .env properly")
        raise
    except OSError as e:
        logger.error(f"Runtime environment variables: \n{cfg}")
        raise PygeoapiEnvError from e
    except LocaleError as e:
        logger.error(f"Runtime language configuration: \n{oapi_content}")
        raise PygeoapiLanguageError from e
    except ProviderConnectionError as e:
        logger.error(f"Runtime environment variables: \n{cfg}")
        logger.error(f"pygeoapi configuration: \n{pygeoapi_conf}")
        logger.error(e)
        raise e
