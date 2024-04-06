"""Command-line interface."""

import os
from pathlib import Path

import typer
from openapi_pydantic.v3.v3_0_3 import OAuthFlow
from openapi_pydantic.v3.v3_0_3 import OAuthFlows
from openapi_pydantic.v3.v3_0_3 import SecurityScheme
from pygeoapi.l10n import LocaleError
from pygeoapi.openapi import generate_openapi_document
from pygeoapi.provider.base import ProviderConnectionError
from rich.console import Console

from app.config.app import configuration as cfg
from app.pygeoapi.openapi import augment_security
from app.utils.pygeoapi_exceptions import PygeoapiEnvError
from app.utils.pygeoapi_exceptions import PygeoapiLanguageError

log_console = Console()
err_console = Console(stderr=True, style="bold red")

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
            err_console.log("pygeoapi variables are not configured")
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
                log_console.log(f"OpenAPI content: {oapi_content}")
                security_schemes = []
                if cfg.OPA_ENABLED:
                    if cfg.API_KEY_ENABLED or cfg.JWKS_ENABLED:
                        raise ValueError(
                            "OPA_ENABLED, JWKS_ENABLED and API_KEY_ENABLED are mutually exclusive"  # noqa
                        )
                    security_schemes = [
                        SecurityScheme(
                            type="openIdConnect",
                            openIdConnectUrl=cfg.OIDC_WELL_KNOWN_ENDPOINT,
                        )
                    ]
                elif cfg.JWKS_ENABLED:
                    if cfg.API_KEY_ENABLED or cfg.OPA_ENABLED:
                        raise ValueError(
                            "OPA_ENABLED, JWKS_ENABLED and API_KEY_ENABLED are mutually exclusive"  # noqa
                        )
                    security_schemes = [
                        SecurityScheme(
                            type="oauth2",
                            name="pygeoapi",
                            flows=OAuthFlows(
                                clientCredentials=OAuthFlow(
                                    tokenUrl=cfg.OAUTH2_TOKEN_ENDPOINT, scopes={}
                                )
                            ),
                        ),
                        SecurityScheme(
                            type="http",
                            name="pygeoapi",
                            scheme="bearer",
                            bearerFormat="JWT",
                        ),
                    ]
                elif cfg.API_KEY_ENABLED:
                    if cfg.OPA_ENABLED:
                        raise ValueError(
                            "OPA_ENABLED and API_KEY_ENABLED are mutually exclusive"
                        )
                    if not cfg.PYGEOAPI_KEY_GLOBAL:
                        raise ValueError("pygeoapi API KEY is missing")
                    os.environ["PYGEOAPI_KEY_GLOBAL"] = cfg.PYGEOAPI_KEY_GLOBAL
                    security_schemes = [
                        SecurityScheme(
                            type="apiKey", name="X-API-KEY", security_scheme_in="header"
                        )
                    ]
                enriched_openapi = augment_security(
                    doc=oapi_content, security_schemes=security_schemes
                )
                openapi_string = enriched_openapi.model_dump_json(
                    by_alias=True, exclude_none=True, indent=2
                )
                oapi_file.write(openapi_string)

    except FileNotFoundError:
        err_console.log("Please configure pygeoapi settings in .env properly")
        raise
    except OSError as e:
        err_console.log(f"Runtime environment variables: \n{cfg}")
        raise PygeoapiEnvError from e
    except LocaleError as e:
        err_console.log(f"Runtime language configuration: \n{oapi_content}")
        raise PygeoapiLanguageError from e
    except ProviderConnectionError as e:
        err_console.log(f"Runtime environment variables: \n{cfg}")
        err_console.log(f"pygeoapi configuration: \n{pygeoapi_conf}")
        err_console.log(e)
        raise e
