"""Command-line interface."""

import os
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from openapi_pydantic.v3.v3_0 import OAuthFlow, OAuthFlows, SecurityScheme
from pygeoapi.l10n import LocaleError
from pygeoapi.openapi import generate_openapi_document
from pygeoapi.provider.base import ProviderConnectionError
from rich.console import Console

from app.config.app import configuration as cfg
from app.pygeoapi.openapi import augment_security
from app.utils.pygeoapi_exceptions import (
    PygeoapiEnvError,
    PygeoapiLanguageError,
)

log_console = Console()
err_console = Console(stderr=True, style="bold red")

app = typer.Typer()


@app.callback()
def main_app_callback() -> None:
    """Commandline interface for fastgeoapi.

    Note: typer.Context parameter removed due to typeguard incompatibility.
    See: https://github.com/agronholm/typeguard/issues/423
    """


@app.command(name="run")
def run(
    host: Annotated[
        str,
        typer.Option("--host", "-h", help="Host to bind the server to"),
    ] = "0.0.0.0",  # noqa: S104  # nosec B104
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port to bind the server to"),
    ] = 5000,
    reload: Annotated[
        bool,
        typer.Option("--reload", "-r", help="Enable auto-reload on code changes"),
    ] = False,
    workers: Annotated[
        int,
        typer.Option("--workers", "-w", help="Number of worker processes"),
    ] = 1,
) -> None:
    """Run the fastgeoapi server.

    This command starts the fastgeoapi server using uvicorn.
    It works both when fastgeoapi is installed as a package
    or when running from a cloned repository.

    Examples
    --------
        fastgeoapi run
        fastgeoapi run --host 127.0.0.1 --port 8000
        fastgeoapi run --reload
        fastgeoapi run -h 0.0.0.0 -p 5000 -r
    """
    log_console.log(f"Starting fastgeoapi server on {host}:{port}")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,  # reload doesn't work with multiple workers
    )


@app.command(name="openapi")
def openapi() -> None:
    """Generate openapi document enriched with security schemes."""
    try:
        # override pygeoapi os variables
        os.environ["PYGEOAPI_CONFIG"] = cfg.PYGEOAPI_CONFIG
        os.environ["PYGEOAPI_OPENAPI"] = cfg.PYGEOAPI_OPENAPI
        os.environ["PYGEOAPI_BASEURL"] = cfg.PYGEOAPI_BASEURL
        os.environ["FASTGEOAPI_CONTEXT"] = cfg.FASTGEOAPI_CONTEXT
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
                            "OPA_ENABLED, JWKS_ENABLED and API_KEY_ENABLED are mutually exclusive"
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
                            "OPA_ENABLED, JWKS_ENABLED and API_KEY_ENABLED are mutually exclusive"
                        )
                    security_schemes = [
                        SecurityScheme(
                            type="oauth2",
                            name="pygeoapi",
                            flows=OAuthFlows(
                                clientCredentials=OAuthFlow(
                                    tokenUrl=cfg.OAUTH2_TOKEN_ENDPOINT,
                                    scopes={},
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
                        raise ValueError("OPA_ENABLED and API_KEY_ENABLED are mutually exclusive")
                    if not cfg.PYGEOAPI_KEY_GLOBAL:
                        raise ValueError("pygeoapi API KEY is missing")
                    os.environ["PYGEOAPI_KEY_GLOBAL"] = cfg.PYGEOAPI_KEY_GLOBAL
                    security_schemes = [
                        SecurityScheme(
                            type="apiKey",
                            name="X-API-KEY",
                            security_scheme_in="header",
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
