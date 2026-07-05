"""Main module."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from app.middleware.proxy import ForwardedLinksMiddleware, MCPMountRootRewriteMiddleware
from app.middleware.pygeoapi import OpenapiSecurityMiddleware
from app.utils.app_exceptions import AppExceptionError, app_exception_handler
from app.utils.openapi_generator import ensure_openapi_file_exists

if TYPE_CHECKING:
    from starlette.applications import Starlette
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


def _build_pygeoapi_subapp() -> Starlette:
    """Build the raw pygeoapi Starlette sub-app with no middleware.

    Used by two callers:

    - :func:`create_app` as the starting point for the externally-mounted
      pygeoapi instance, which then has auth/security middleware wrapped
      around it.
    - :func:`create_mcp_server` (when no ``api_client`` is provided) as
      the target of an ``httpx.ASGITransport``, so the MCP server can
      issue in-process requests to pygeoapi without going through the
      network or any middleware. This replaces the previous
      ``X-MCP-Internal-Key`` header bypass.

    The function is intentionally lean: it only assembles the routing,
    leaving every middleware concern to the caller.
    """
    try:
        pygeoapi_conf = Path.cwd() / cfg.PYGEOAPI_CONFIG

        from pygeoapi.starlette_app import APP as PYGEOAPI_APP
        from pygeoapi.starlette_app import url_prefix
        from starlette.applications import Starlette
        from starlette.routing import Mount

        from app.utils.pygeoapi_utils import patch_route

        static_route = PYGEOAPI_APP.routes[0]
        api_app = PYGEOAPI_APP.routes[1].app
        api_routes = api_app.routes

        patched_routes = tuple(patch_route(r) for r in api_routes)

        return Starlette(
            routes=[
                static_route,
                Mount(url_prefix or "/", routes=list(patched_routes)),
            ],
        )
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

    # Build the externally-mounted pygeoapi sub-app and wrap it with the
    # middleware stack appropriate to the current auth mode.
    patched_app = _build_pygeoapi_subapp()
    if cfg.FASTGEOAPI_REVERSE_PROXY:
        patched_app.add_middleware(ForwardedLinksMiddleware)

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
def create_mcp_server(api_client: httpx.AsyncClient | None = None):
    """Create MCP server from the OGC API OpenAPI specification.

    Parameters
    ----------
    api_client : httpx.AsyncClient | None
        Optional async client for MCP to make API requests. If not provided,
        a new client will be created. When provided, the caller is responsible
        for managing the client lifecycle (closing it when done).

    Returns
    -------
        Tuple of (mcp_server, mcp_app, well_known_routes, api_client) where:
        - well_known_routes are the OAuth discovery routes to mount at root level
        - api_client is the httpx.AsyncClient used by MCP (for lifecycle management)
    """
    from app.utils.openapi_resolver import resolve_external_refs

    # Load OpenAPI spec from the pygeoapi-generated YAML file
    pygeoapi_openapi_path = Path.cwd() / cfg.PYGEOAPI_OPENAPI
    if not pygeoapi_openapi_path.exists():
        logger.warning(f"OpenAPI file not found: {pygeoapi_openapi_path}. MCP disabled.")
        return None, None, [], None

    with pygeoapi_openapi_path.open() as f:
        base_spec = yaml.safe_load(f)

    # Resolve external $ref references with disk caching
    cache_dir = Path.cwd() / ".cache" / "openapi_refs"
    logger.info("Resolving external OpenAPI references...")
    openapi_spec = resolve_external_refs(base_spec, cache_dir=cache_dir)
    logger.info("OpenAPI references resolved successfully")

    # When no client is provided, build a default that routes MCP→pygeoapi
    # calls in-process via httpx.ASGITransport. The target is a *raw*
    # pygeoapi sub-app with no auth/security middleware, so no bypass is
    # needed: the middleware chain simply isn't on this path.
    #
    # `base_url` uses a virtual hostname (not loopback, not an IP) so that
    # even if the client object is somehow leaked, the request can't reach
    # an external network — it can only be served by the ASGI transport.
    # The raw sub-app's routes live at the root (no FASTGEOAPI_CONTEXT
    # prefix), so the base URL must not include the context either.
    if api_client is None:
        api_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_build_pygeoapi_subapp()),
            base_url="http://mcp-internal",
            timeout=30.0,
        )

    # Configure OIDC authentication if JWKS is enabled
    # Uses mcpauth for provider-agnostic configuration and JWT validation
    auth = None
    well_known_routes = []
    if cfg.JWKS_ENABLED and cfg.OIDC_WELL_KNOWN_ENDPOINT:
        from app.auth.mcp_auth_provider import configure_mcp_auth

        # Determine base URL for MCP server (with trailing slash for IdP compatibility)
        mcp_base_url = f"http://{cfg.HOST}:{cfg.PORT}/mcp/"
        if hasattr(cfg, "APP_URI") and cfg.APP_URI:
            mcp_base_url = f"{cfg.APP_URI.rstrip('/')}/mcp/"

        logger.info(f"Configuring MCP with OIDC authentication via {cfg.OIDC_WELL_KNOWN_ENDPOINT}")

        # Use mcpauth for provider-agnostic OIDC configuration
        # This handles Logto, Auth0, Keycloak, and other IdPs without custom code
        auth, well_known_routes = configure_mcp_auth(
            oidc_well_known_endpoint=cfg.OIDC_WELL_KNOWN_ENDPOINT,
            client_id=cfg.OIDC_CLIENT_ID,
            client_secret=cfg.OIDC_CLIENT_SECRET,
            mcp_base_url=mcp_base_url,
            # `offline_access` is required so the IdP issues a refresh token;
            # without it the MCP client cannot refresh silently and re-runs the
            # full authorization (browser + consent) on every access-token
            # expiry — which both reopens the consent page and breaks the MCP
            # session continuity mid-conversation.
            scopes=["openid", "profile", "email", "offline_access"],
            consent_mode=getattr(cfg, "FASTGEOAPI_MCP_CONSENT_MODE", None),
            # Client-facing token TTL decoupled from the IdP `expires_in`
            # (defaults to 24h inside `configure_mcp_auth`); reduces re-auth
            # friction for clients that keep tokens only in memory.
            access_token_expiry_seconds=getattr(
                cfg, "FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS", None
            ),
        )

    # Create MCP server from OpenAPI spec
    mcp_server = FastMCP.from_openapi(
        openapi_spec=openapi_spec,
        client=api_client,
        name="OGC API MCP",
        auth=auth,
    )

    return (
        mcp_server,
        mcp_server.http_app(path="/"),
        well_known_routes,
        api_client,
    )


# Ensure OpenAPI file exists
ensure_openapi_file_exists()

# Create the main app, optionally with MCP server
if cfg.FASTGEOAPI_WITH_MCP:
    from contextlib import asynccontextmanager

    mcp, mcp_app, well_known_routes, mcp_api_client = create_mcp_server()
    if mcp_app is not None:

        @asynccontextmanager
        async def combined_lifespan(app):
            """Combined lifespan that manages both MCP app and httpx client lifecycle.

            This ensures the httpx.AsyncClient is properly closed when the app
            shuts down, preventing resource leaks (open connections, file descriptors).
            """
            # Use MCP app's lifespan if available
            if mcp_app.lifespan:
                async with mcp_app.lifespan(app):
                    try:
                        yield
                    finally:
                        # Clean up the httpx client when app shuts down
                        if mcp_api_client is not None:
                            await mcp_api_client.aclose()
                            logger.info("MCP API client closed")
            else:
                try:
                    yield
                finally:
                    # Clean up the httpx client when app shuts down
                    if mcp_api_client is not None:
                        await mcp_api_client.aclose()
                        logger.info("MCP API client closed")

        app = create_app(lifespan=combined_lifespan)

        # Mount OAuth well-known routes at root level per RFC 8414 and RFC 9728
        # These routes must be accessible at /.well-known/* not /mcp/.well-known/*
        # Mount these BEFORE /mcp to ensure they take precedence
        if well_known_routes:
            from starlette.routing import Route

            # Add well-known routes directly to the app's router
            # The routes have paths like /.well-known/oauth-authorization-server/mcp
            for route in well_known_routes:
                app.router.routes.insert(0, route)
                logger.info(f"Mounted OAuth route at root: {route.path}")
                # Clients that strip the trailing slash from the server URL
                # (e.g. Claude Desktop's connector UI) derive slash-less
                # discovery URLs. Serve those directly: relying on
                # redirect_slashes emits a Location that downgrades to
                # http:// when the proxy scheme isn't rewritten.
                if isinstance(route, Route) and route.path.endswith("/"):
                    alias = Route(
                        route.path.rstrip("/"),
                        endpoint=route.endpoint,
                        methods=list(route.methods or []),
                    )
                    app.router.routes.insert(0, alias)
                    logger.info(f"Mounted OAuth route alias at root: {alias.path}")

        app.mount("/mcp", mcp_app)
        # Starlette's Mount only matches "/mcp/..." — a bare "/mcp" falls
        # through to the outer router's redirect_slashes, whose Location
        # downgrades to http:// behind an unrewritten reverse proxy and
        # breaks POSTs from clients that strip the trailing slash (e.g.
        # Claude Desktop's connector UI). Rewrite the path before routing.
        app.add_middleware(MCPMountRootRewriteMiddleware)
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
