"""Main module."""

import os
import sys
from pathlib import Path
from typing import Any

import loguru
import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi_opa import OPAMiddleware
from loguru import logger
from mangum import Mangum
from openapi_pydantic.v3.v3_0 import OAuthFlow, OAuthFlows, SecurityScheme
from pygeoapi.l10n import LocaleError
from pygeoapi.openapi import generate_openapi_document
from pygeoapi.provider.base import ProviderConnectionError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.config.app import configuration as cfg
from app.config.logging import create_logger
from app.middleware.oauth2 import Oauth2Middleware
from app.middleware.proxy import ForwardedLinksMiddleware
from app.middleware.pygeoapi import OpenapiSecurityMiddleware
from app.utils.app_exceptions import AppExceptionError, app_exception_handler
from app.utils.pygeoapi_exceptions import (
    PygeoapiEnvError,
    PygeoapiLanguageError,
)
from app.utils.request_exceptions import (
    http_exception_handler,
    request_validation_exception_handler,
)

if cfg.LOG_LEVEL == "debug":
    logger.remove()
    logger.add(
        sys.stdout,
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | {level} | <level>{message}</level>",
    )


class FastGeoAPI(FastAPI):
    """Subclass of FastAPI that possesses a logger attribute."""

    def __init__(self, **extra: Any):
        """Included the self.logger attribute."""
        super().__init__(**extra)
        self.logger: loguru.Logger = logger


def create_app():
    """Handle application creation."""
    app = FastGeoAPI(title="fastgeoapi", root_path=cfg.ROOT_PATH, debug=True)

    # Set all CORS enabled origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(StarletteHTTPException)
    async def custom_http_exception_handler(request, e):
        return await http_exception_handler(request, e)

    @app.exception_handler(RequestValidationError)
    async def custom_validation_exception_handler(request, e):
        return await request_validation_exception_handler(request, e)

    @app.exception_handler(AppExceptionError)
    async def custom_app_exception_handler(request, e):
        return await app_exception_handler(request, e)

    try:
        # override pygeoapi os variables
        # Pydantic will validate these are set at config instantiation time
        os.environ["PYGEOAPI_CONFIG"] = cfg.PYGEOAPI_CONFIG
        os.environ["PYGEOAPI_OPENAPI"] = cfg.PYGEOAPI_OPENAPI

        # fill pygeoapi configuration with host, port, base url and context
        os.environ["HOST"] = cfg.HOST
        os.environ["PORT"] = cfg.PORT
        os.environ["PYGEOAPI_BASEURL"] = cfg.PYGEOAPI_BASEURL
        os.environ["FASTGEOAPI_CONTEXT"] = cfg.FASTGEOAPI_CONTEXT

        # prepare pygeoapi openapi file if it doesn't exist
        pygeoapi_conf = Path.cwd() / os.environ["PYGEOAPI_CONFIG"]
        pygeoapi_oapi = Path.cwd() / os.environ["PYGEOAPI_OPENAPI"]
        if not (os.environ["PYGEOAPI_CONFIG"] and os.environ["PYGEOAPI_OPENAPI"]):
            logger.error("pygeoapi variables are not configured")
            raise PygeoapiEnvError("PYGEOAPI_CONFIG and PYGEOAPI_OPENAPI are not set")
        else:
            # fill pygeoapi configuration with host, port, base url and context
            os.environ["HOST"] = cfg.HOST
            os.environ["PORT"] = cfg.PORT
            os.environ["PYGEOAPI_BASEURL"] = cfg.PYGEOAPI_BASEURL
            os.environ["FASTGEOAPI_CONTEXT"] = cfg.FASTGEOAPI_CONTEXT

            # prepare pygeoapi openapi file if it doesn't exist
            pygeoapi_conf = Path.cwd() / os.environ["PYGEOAPI_CONFIG"]
            pygeoapi_oapi = Path.cwd() / os.environ["PYGEOAPI_OPENAPI"]
            if not pygeoapi_oapi.exists():
                pygeoapi_oapi.write_text(data="")
                with pygeoapi_oapi.open(mode="w") as oapi_file:
                    oapi_content = generate_openapi_document(
                        pygeoapi_conf,
                        output_format="yaml",
                    )
                    logger.debug(f"OpenAPI content: \n{oapi_content}")
                    oapi_file.write(oapi_content)

            # import pygeoapi starlette application once pygeoapi configuration
            # are set and prepare the objects to override some core behavior
            from pygeoapi.starlette_app import APP as PYGEOAPI_APP
            from pygeoapi.starlette_app import url_prefix
            from starlette.applications import Starlette
            from starlette.routing import Mount

            from app.utils.pygeoapi_utils import patch_route

            static_route = PYGEOAPI_APP.routes[0]
            api_app = PYGEOAPI_APP.routes[1].app
            api_routes = api_app.routes

            patched_routes = ()
            for api_route in api_routes:
                api_route_ = patch_route(api_route)
                patched_routes += (api_route_,)

            patched_app = Starlette(
                routes=[
                    static_route,
                    Mount(url_prefix or "/", routes=list(patched_routes)),
                ],
            )
            if cfg.FASTGEOAPI_REVERSE_PROXY:
                patched_app.add_middleware(ForwardedLinksMiddleware)

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

    # Add OPAMiddleware to the pygeoapi app
    security_schemes = []
    if cfg.OPA_ENABLED:
        if cfg.API_KEY_ENABLED or cfg.JWKS_ENABLED:
            raise ValueError("OPA_ENABLED, JWKS_ENABLED and API_KEY_ENABLED are mutually exclusive")
        from app.config.auth import auth_config

        patched_app.add_middleware(OPAMiddleware, config=auth_config)

        security_schemes = [
            SecurityScheme(
                type="openIdConnect",
                openIdConnectUrl=cfg.OIDC_WELL_KNOWN_ENDPOINT,
            )
        ]
    # Add Oauth2Middleware to the pygeoapi app
    elif cfg.JWKS_ENABLED:
        if cfg.API_KEY_ENABLED or cfg.OPA_ENABLED:
            raise ValueError("OPA_ENABLED, JWKS_ENABLED and API_KEY_ENABLED are mutually exclusive")
        from app.config.auth import auth_config

        patched_app.add_middleware(Oauth2Middleware, config=auth_config)

        security_schemes = [
            SecurityScheme(
                type="oauth2",
                name="pygeoapi",
                flows=OAuthFlows(
                    clientCredentials=OAuthFlow(tokenUrl=cfg.OAUTH2_TOKEN_ENDPOINT, scopes={})
                ),
            ),
            SecurityScheme(
                type="http",
                name="pygeoapi",
                scheme="bearer",
                bearerFormat="JWT",
            ),
        ]
    # Add AuthorizerMiddleware to the pygeoapi app
    elif cfg.API_KEY_ENABLED:
        if cfg.OPA_ENABLED:
            raise ValueError("OPA_ENABLED and API_KEY_ENABLED are mutually exclusive")
        if not cfg.PYGEOAPI_KEY_GLOBAL:
            raise ValueError("pygeoapi API KEY is missing")
        from fastapi_key_auth import AuthorizerMiddleware

        os.environ["PYGEOAPI_KEY_GLOBAL"] = cfg.PYGEOAPI_KEY_GLOBAL

        patched_app.add_middleware(
            AuthorizerMiddleware,
            public_paths=[f"{cfg.FASTGEOAPI_CONTEXT}/openapi"],
            key_pattern="PYGEOAPI_KEY_",
        )

        security_schemes = [
            SecurityScheme(type="apiKey", name="X-API-KEY", security_scheme_in="header")
        ]

    if security_schemes:
        patched_app.add_middleware(OpenapiSecurityMiddleware, security_schemes=security_schemes)

    app.mount(path=cfg.FASTGEOAPI_CONTEXT, app=patched_app)

    app.logger = create_logger(name="app.main")

    return app


app = create_app()

app.logger.debug(f"Global config: {cfg.__repr__()}")

if cfg.AWS_LAMBDA_DEPLOY:
    # to make it work with Amazon Lambda,
    # we create a handler object
    handler = Mangum(app)

if __name__ == "__main__":
    uvicorn.run(app, port=cfg.PORT)
