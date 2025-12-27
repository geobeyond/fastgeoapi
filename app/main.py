"""Main module."""

import os
import sys
from pathlib import Path
from typing import Any

import httpx
import loguru
import uvicorn
import yaml
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi_opa import OPAMiddleware
from fastmcp import FastMCP
from loguru import logger
from mangum import Mangum
from openapi_pydantic.v3.v3_0 import OAuthFlow, OAuthFlows, SecurityScheme
from pygeoapi.l10n import LocaleError
from pygeoapi.provider.base import ProviderConnectionError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from app.config.app import configuration as cfg
from app.config.logging import create_logger
from app.middleware.oauth2 import Oauth2Middleware
from app.middleware.proxy import ForwardedLinksMiddleware
from app.middleware.pygeoapi import OpenapiSecurityMiddleware
from app.utils.app_exceptions import AppExceptionError, app_exception_handler
from app.utils.openapi_generator import ensure_openapi_file_exists
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


def create_app(lifespan=None):
    """Handle application creation.

    Args:
        lifespan: Optional lifespan context manager for the app.
    """
    app = FastGeoAPI(
        title="fastgeoapi",
        root_path=cfg.ROOT_PATH,
        debug=True,
        lifespan=lifespan,
    )

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
        # Ensure OpenAPI file exists (environment variables are set by ensure_openapi_file_exists)
        pygeoapi_conf = Path.cwd() / cfg.PYGEOAPI_CONFIG

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
        logger.error(f"Locale error during pygeoapi initialization: {e}")
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


# MCP Server setup using OpenAPI spec from pygeoapi YAML file
def create_mcp_server():
    """Create MCP server from the OGC API OpenAPI specification.

    Returns
    -------
        Tuple of (mcp_server, mcp_app, well_known_routes) where well_known_routes
        are the OAuth discovery routes that need to be mounted at root level.
    """
    from app.utils.openapi_resolver import resolve_external_refs

    # Load OpenAPI spec from the pygeoapi-generated YAML file
    pygeoapi_openapi_path = Path.cwd() / cfg.PYGEOAPI_OPENAPI
    if not pygeoapi_openapi_path.exists():
        logger.warning(f"OpenAPI file not found: {pygeoapi_openapi_path}. MCP disabled.")
        return None, None, []

    with pygeoapi_openapi_path.open() as f:
        base_spec = yaml.safe_load(f)

    # Resolve external $ref references with disk caching
    cache_dir = Path.cwd() / ".cache" / "openapi_refs"
    logger.info("Resolving external OpenAPI references...")
    openapi_spec = resolve_external_refs(base_spec, cache_dir=cache_dir)
    logger.info("OpenAPI references resolved successfully")

    # Base URL for API calls
    api_base_url = f"http://{cfg.HOST}:{cfg.PORT}{cfg.FASTGEOAPI_CONTEXT}"

    # Generate a secret key for internal MCP-to-API calls
    # This allows the OAuth2 middleware to bypass auth for internal requests
    import secrets

    mcp_internal_key = secrets.token_urlsafe(32)

    # Create async client for MCP to make API requests
    # Include the internal key header so the middleware can identify MCP requests
    api_client = httpx.AsyncClient(
        base_url=api_base_url,
        timeout=30.0,
        headers={"X-MCP-Internal-Key": mcp_internal_key},
    )

    # Store the key in config for the middleware to access
    cfg.MCP_INTERNAL_KEY = mcp_internal_key

    # Configure OIDC authentication if JWKS is enabled
    auth = None
    well_known_routes = []
    if cfg.JWKS_ENABLED and cfg.OIDC_WELL_KNOWN_ENDPOINT:
        import hashlib
        from base64 import urlsafe_b64encode
        from typing import Any
        from urllib.parse import urlencode

        from fastmcp.server.auth.oidc_proxy import OIDCProxy
        from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier

        class CustomOIDCProxy(OIDCProxy):
            """Custom OIDC Proxy that doesn't forward the resource parameter to Logto.

            IdP returns access_denied for third-party apps (like mcp-remote using
            Dynamic Client Registration) that request API Resources without explicit
            permission grants. By not forwarding the resource parameter, we only use
            OIDC for authentication (ID token), not for API authorization.
            """

            def _build_upstream_authorize_url(
                self, txn_id: str, transaction: dict[str, Any]
            ) -> str:
                """Override to not forward the resource parameter to the IdP."""
                query_params: dict[str, Any] = {
                    "response_type": "code",
                    "client_id": self._upstream_client_id,
                    "redirect_uri": f"{str(self.base_url).rstrip('/')}{self._redirect_path}",
                    "state": txn_id,
                }

                scopes_to_use = transaction.get("scopes") or self.required_scopes or []
                if scopes_to_use:
                    query_params["scope"] = " ".join(scopes_to_use)

                # If PKCE forwarding was enabled, include the proxy challenge
                proxy_code_verifier = transaction.get("proxy_code_verifier")
                if proxy_code_verifier:
                    challenge_bytes = hashlib.sha256(proxy_code_verifier.encode()).digest()
                    proxy_code_challenge = urlsafe_b64encode(challenge_bytes).decode().rstrip("=")
                    query_params["code_challenge"] = proxy_code_challenge
                    query_params["code_challenge_method"] = "S256"

                # NOTE: We intentionally don't forward the resource parameter to the IdP
                # because third-party apps cannot access API Resources without explicit
                # permission grants in IdP's console.

                # Extra configured parameters (but filter out 'resource' if present)
                if self._extra_authorize_params:
                    extra_params = {
                        k: v for k, v in self._extra_authorize_params.items() if k != "resource"
                    }
                    query_params.update(extra_params)

                separator = "&" if "?" in self._upstream_authorization_endpoint else "?"
                return (
                    f"{self._upstream_authorization_endpoint}{separator}{urlencode(query_params)}"
                )

        # Determine base URL for MCP server (with trailing slash for the IdP compatibility)
        mcp_base_url = f"http://{cfg.HOST}:{cfg.PORT}/mcp/"
        if hasattr(cfg, "APP_URI") and cfg.APP_URI:
            mcp_base_url = f"{cfg.APP_URI.rstrip('/')}/mcp/"

        # Extract IdP issuer URL for introspection endpoint
        # IdP's introspection endpoint is at /oidc/token/introspection
        idp_issuer = cfg.OIDC_WELL_KNOWN_ENDPOINT.replace(
            "/oidc/.well-known/openid-configuration", ""
        )
        introspection_url = f"{idp_issuer}/oidc/token/introspection"

        logger.info(f"Configuring MCP with OIDC authentication via {cfg.OIDC_WELL_KNOWN_ENDPOINT}")
        logger.info(f"Using token introspection endpoint: {introspection_url}")

        # Use IntrospectionTokenVerifier for opaque tokens from IdP
        # IdP returns opaque tokens when no API Resource is requested
        token_verifier = IntrospectionTokenVerifier(
            introspection_url=introspection_url,
            client_id=cfg.OIDC_CLIENT_ID,
            client_secret=cfg.OIDC_CLIENT_SECRET,
            base_url=mcp_base_url,
        )

        auth = CustomOIDCProxy(
            config_url=cfg.OIDC_WELL_KNOWN_ENDPOINT,
            client_id=cfg.OIDC_CLIENT_ID,
            client_secret=cfg.OIDC_CLIENT_SECRET,
            base_url=mcp_base_url,
            # Use introspection for opaque token validation
            token_verifier=token_verifier,
            # Pass OIDC scopes to IdP
            extra_authorize_params={"scope": "openid profile email"},
        )

        # Add standard OIDC scopes to supported scopes for mcp-remote compatibility
        # mcp-remote requests: openid, profile, email
        if auth.client_registration_options:
            auth.client_registration_options.valid_scopes = [
                "openid",
                "profile",
                "email",
            ]

        # Extract well-known routes that need to be mounted at root level
        # per RFC 8414 and RFC 9728
        # Use mcp_path="/" because the MCP app is created with path="/" internally,
        # and will be mounted at /mcp on the main app. The base_url already includes /mcp.
        well_known_routes = auth.get_well_known_routes(mcp_path="/")
        logger.info(f"Extracted {len(well_known_routes)} OAuth well-known routes for root mounting")

    # Create MCP server from OpenAPI spec
    mcp_server = FastMCP.from_openapi(
        openapi_spec=openapi_spec,
        client=api_client,
        name="OGC API MCP",
        auth=auth,
    )

    return mcp_server, mcp_server.http_app(path="/"), well_known_routes


# Ensure OpenAPI file exists
ensure_openapi_file_exists()

# Create the main app, optionally with MCP server
if cfg.FASTGEOAPI_WITH_MCP:
    mcp, mcp_app, well_known_routes = create_mcp_server()
    if mcp_app is not None:
        app = create_app(lifespan=mcp_app.lifespan)

        # Mount OAuth well-known routes at root level per RFC 8414 and RFC 9728
        # These routes must be accessible at /.well-known/* not /mcp/.well-known/*
        # Mount these BEFORE /mcp to ensure they take precedence
        if well_known_routes:
            # Add well-known routes directly to the app's router
            # The routes have paths like /.well-known/oauth-authorization-server/mcp
            for route in well_known_routes:
                app.router.routes.insert(0, route)
                logger.info(f"Mounted OAuth route at root: {route.path}")

        app.mount("/mcp", mcp_app)
        logger.info("MCP server mounted at /mcp")
    else:
        app = create_app()
else:
    app = create_app()

app.logger.debug(f"Global config: {cfg.__repr__()}")

if cfg.AWS_LAMBDA_DEPLOY:
    # to make it work with Amazon Lambda,
    # we create a handler object
    handler = Mangum(app)

if __name__ == "__main__":
    uvicorn.run(app, port=cfg.PORT)
