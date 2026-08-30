"""Command-line interface."""

import json
import os
from pathlib import PurePosixPath
from typing import Annotated

import typer
import uvicorn
from rich.console import Console

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
    ] = "0.0.0.0",  # ruff: ignore[hardcoded-bind-all-interfaces]  # nosec B104
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
        # Interpolation inputs for ``${VAR}`` placeholders inside the
        # pygeoapi config (resolved by pygeoapi's yaml_load). The config
        # itself travels as bytes through the storage layer: local paths
        # and s3://, gs://, az:// URLs share one code path.
        # All imported here, not at module level. Reaching any of them
        # pulls in fastgeoapi's settings, and building those demands a
        # configured fastgeoapi — HOST, PORT and the rest — while
        # `config edit` is meant to work for someone who has only
        # pygeoapi and a document to fix. At module level the command
        # died on two missing variables before reading its own arguments.
        from openapi_pydantic.v3.v3_0 import (
            OAuthFlow,
            OAuthFlows,
            SecurityScheme,
        )
        from pygeoapi.l10n import LocaleError
        from pygeoapi.provider.base import ProviderConnectionError

        # Imported here, not at module level: building these settings
        # demands a configured fastgeoapi — HOST, PORT and the rest — and
        # `config edit` is meant to work for someone who has only
        # pygeoapi and a document to fix. A module-level import made the
        # command die on two missing variables before it had read its own
        # arguments.
        from app.config.app import configuration as cfg
        from app.config.source import load_config_source
        from app.provider.storage import StorageBridge, load_store, split_source
        from app.pygeoapi.factory import build_openapi
        from app.pygeoapi.openapi import augment_security

        os.environ["PYGEOAPI_CONFIG"] = cfg.PYGEOAPI_CONFIG
        os.environ["PYGEOAPI_OPENAPI"] = cfg.PYGEOAPI_OPENAPI
        os.environ["PYGEOAPI_BASEURL"] = cfg.PYGEOAPI_BASEURL
        os.environ["FASTGEOAPI_CONTEXT"] = cfg.FASTGEOAPI_CONTEXT
        os.environ["HOST"] = cfg.HOST
        os.environ["PORT"] = cfg.PORT

        if not (cfg.PYGEOAPI_CONFIG and cfg.PYGEOAPI_OPENAPI):
            err_console.log("pygeoapi variables are not configured")
            raise PygeoapiEnvError("PYGEOAPI_CONFIG and PYGEOAPI_OPENAPI are not set")
        else:
            document = load_config_source(cfg.PYGEOAPI_CONFIG)
            pygeoapi_conf = document.source
            oapi_content = json.dumps(build_openapi(document.config), default=str)
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
            enriched_openapi = augment_security(doc=oapi_content, security_schemes=security_schemes)
            openapi_string = enriched_openapi.model_dump_json(
                by_alias=True, exclude_none=True, indent=2
            )
            # The output goes through the storage Protocol too, so the
            # target can be a local path or a bucket URL. The historical
            # ``.json`` suffix applies to the key, never to the base.
            base, key = split_source(cfg.PYGEOAPI_OPENAPI)
            json_key = str(PurePosixPath(key).with_suffix(".json"))
            StorageBridge(load_store(base)).write(json_key, openapi_string.encode("utf-8"))
            log_console.log(f"OpenAPI document written to {base}{json_key}")

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


config_app = typer.Typer(help="Work with the pygeoapi configuration document.")
app.add_typer(config_app, name="config")


@config_app.command(name="edit")
def config_edit(
    source: Annotated[
        str | None,
        typer.Option("--source", "-s", help="Configuration document to edit"),
    ] = None,
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Port to serve the editor on"),
    ] = 8765,
) -> None:
    """Edit the configuration document through a local editor.

    This is what keeps the two roles of ADR-0008 apart. The application
    it serves mounts the editor and **not** the reload webhook: writing
    a configuration and putting it into service are different powers,
    and one surface holding both would mean whoever reaches it decides
    what the server serves.

    It stays on loopback and prints its per-run secret, which callers
    send as a header. The secret never goes in a URL: one there would
    outlive the session in browser history, `Referer` and logs.

    Examples
    --------
        fastgeoapi config edit
        fastgeoapi config edit --source s3://bucket/pygeoapi-config.yml
        fastgeoapi config edit --port 9000
    """
    import app.editor.app as editor_app
    from app.editor.app import EDITOR_TOKEN_HEADER, build_authoring_app

    host = "127.0.0.1"
    editor = build_authoring_app(host=host, source=source)
    token = editor.state.editor_token
    base = f"http://{host}:{port}"

    log_console.log(f"Editing {editor.state.editor_source}")
    # Plain output, not rich: these lines are meant to be copied, and
    # rich would wrap the token across lines at the terminal width.
    #
    # The secret is NOT put in a URL. A URL carrying it would survive in
    # browser history, in `Referer` towards anything the page loads, in
    # any proxy log and in the shell history that printed it — which is
    # the very reason the API takes it in a header. The page asks for it
    # instead, and exchanges it once for an HttpOnly cookie, so it never
    # travels in an address bar.
    typer.echo(f"Editor listening on {base}")
    typer.echo(f"Token: {token}")
    typer.echo("")
    if (editor_app.DEFAULT_PAGE / "index.html").is_file():
        typer.echo(f"  Open {base} and paste the token when it asks.")
    else:
        # A working API and no page is an ordinary state — the API came
        # first on purpose — so it is said here rather than discovered as
        # a puzzling browser tab.
        typer.echo("  The page is not compiled in this installation.")
        typer.echo("  To build it: cd frontend && npm install && npm run build")
    typer.echo("")
    typer.echo(f"  curl -H '{EDITOR_TOKEN_HEADER}: {token}' {base}/editor/config")

    uvicorn.run(editor, host=host, port=port)
