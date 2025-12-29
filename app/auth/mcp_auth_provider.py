"""MCP Authentication Provider using mcpauth for multi-IdP support.

This module provides a provider-agnostic authentication setup for MCP servers
using the mcpauth library for OIDC configuration and JWT validation.

It supports multiple identity providers (Logto, Auth0, Keycloak, etc.) without
requiring custom code for each provider.
"""

import hashlib
import json
from base64 import urlsafe_b64encode
from typing import Any
from urllib.parse import urlencode

from fastmcp.server.auth.oidc_proxy import OIDCProxy
from loguru import logger
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import (
    AuthenticatedUser,
    BearerAuthBackend,
)
from mcp.server.auth.middleware.bearer_auth import (
    RequireAuthMiddleware as SDKRequireAuthMiddleware,
)
from mcp.server.auth.provider import AccessToken
from mcpauth.config import AuthServerType
from mcpauth.utils import fetch_server_config
from pydantic import AnyHttpUrl
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.types import Receive, Scope, Send


class MCPAuthTokenVerifier:
    """Token verifier that uses mcpauth for JWT validation.

    This provides provider-agnostic token validation using mcpauth's
    built-in JWT verification with automatic JWKS fetching.

    Returns AccessToken objects as required by FastMCP's auth system.
    """

    def __init__(
        self,
        verify_fn,
        client_id: str,
        client_secret: str,
        base_url: str,
        required_scopes: list[str] | None = None,
    ):
        """Initialize the token verifier.

        Parameters
        ----------
        verify_fn : callable
            The JWT verification function from mcpauth.
        client_id : str
            The OAuth client ID.
        client_secret : str
            The OAuth client secret.
        base_url : str
            The base URL for the MCP server.
        required_scopes : list[str], optional
            The required scopes for token validation.
        """
        self.verify_fn = verify_fn
        self.base_url = base_url
        # Required by FastMCP's OIDCProxy
        self.client_id = client_id
        self.client_secret = client_secret
        self.introspection_url = None  # Not used for JWT validation
        self.required_scopes = required_scopes or []

    async def verify_token(self, token: str) -> AccessToken | None:
        """Verify token using mcpauth's JWT validation.

        Parameters
        ----------
        token : str
            The JWT token to verify.

        Returns
        -------
        AccessToken | None
            AccessToken object if valid, None if invalid or expired.
        """
        try:
            auth_info = self.verify_fn(token)
            claims = auth_info.claims

            # Extract client_id from claims or use configured client_id
            client_id = claims.get("client_id") or claims.get("azp") or self.client_id

            # Extract scopes as a list
            scope_str = claims.get("scope", "")
            scopes = scope_str.split() if scope_str else []

            # Get expiration time
            expires_at = claims.get("exp")
            if expires_at is not None:
                expires_at = int(expires_at)

            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=expires_at,
            )
        except Exception as e:
            logger.warning(f"Token verification failed: {e}")
            return None


class TrustingUpstreamTokenVerifier:
    """Token verifier for IdPs that return opaque tokens (not JWTs).

    Some IdPs like Logto return opaque tokens when no API Resource is requested.
    These tokens cannot be validated locally with JWT verification because they
    are not JWTs - they're opaque strings that only the IdP can interpret.

    This verifier trusts the upstream token because:
    1. It was obtained via a secure OAuth 2.0 code exchange with the IdP
    2. FastMCP stores it encrypted after receiving it from the IdP's token endpoint
    3. Before this verifier is called, FastMCP has already validated its own JWT
       (signature, expiry, issuer) which references this upstream token
    4. The upstream token is looked up via a cryptographically secure JTI mapping

    For IdPs that support token introspection (RFC 7662), a more robust approach
    would be to call the introspection endpoint. However, not all IdPs expose
    this endpoint, and for OIDC-only flows it's not required.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        required_scopes: list[str] | None = None,
    ):
        """Initialize the trusting token verifier.

        Parameters
        ----------
        client_id : str
            The OAuth client ID.
        client_secret : str
            The OAuth client secret.
        required_scopes : list[str], optional
            The scopes to include in the AccessToken.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.required_scopes = required_scopes or []
        # Not used but required by OIDCProxy interface
        self.introspection_url = None

    async def verify_token(self, token: str) -> AccessToken:
        """Accept the upstream opaque token as valid.

        Parameters
        ----------
        token : str
            The upstream opaque token from the IdP.

        Returns
        -------
        AccessToken
            An AccessToken representing the validated upstream token.
        """
        logger.debug("Accepting upstream opaque token (validated during OAuth exchange)")
        return AccessToken(
            token=token,
            client_id=self.client_id,
            scopes=self.required_scopes,
            expires_at=None,  # Expiry is managed by FastMCP's JWT
        )


class RFC6750CompliantAuthMiddleware(SDKRequireAuthMiddleware):
    """Authentication middleware compliant with RFC 6750.

    This middleware fixes a bug in the MCP SDK where it returns 'invalid_token'
    error even when NO token is provided. Per RFC 6750 Section 3.1:

    - "invalid_token": The access token provided is expired, revoked,
      malformed, or invalid for other reasons.

    When no token is provided, the response should be a simple 401 with
    WWW-Authenticate header, without the 'invalid_token' error code.

    This distinction matters for mcp-remote because:
    1. When it receives 'invalid_token', the SDK interprets this as InvalidClientError
    2. This triggers invalidateCredentials("all") which DELETES client_info.json
    3. After browser auth completes, mcp-remote has no client info to exchange the code

    By returning a proper response for missing tokens, mcp-remote correctly
    initiates the OAuth flow without deleting its client registration.
    """

    def __init__(
        self,
        app: Any,
        required_scopes: list[str],
        resource_metadata_url: AnyHttpUrl | None = None,
    ):
        """Initialize the middleware.

        Parameters
        ----------
        app : Any
            The ASGI application to wrap.
        required_scopes : list[str]
            List of scopes required for authenticated requests.
        resource_metadata_url : AnyHttpUrl | None
            URL to the protected resource metadata for WWW-Authenticate header.
        """
        super().__init__(app, required_scopes, resource_metadata_url)
        self._token_was_provided = False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process the request and check authentication.

        This method checks if a token was provided before delegating to
        the parent class. This allows us to return different errors for
        "no token" vs "invalid token".
        """
        if scope["type"] == "http":
            # Check if Authorization header with Bearer token was provided
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode()
            self._token_was_provided = auth_header.lower().startswith("bearer ")

        # Get auth info from scope (set by BearerAuthBackend)
        auth_user = scope.get("user")

        if not isinstance(auth_user, AuthenticatedUser):
            # Authentication failed - determine the right error
            if self._token_was_provided:
                # Token was provided but invalid -> invalid_token
                await self._send_auth_error(
                    send,
                    status_code=401,
                    error="invalid_token",
                    description="The provided bearer token is invalid, expired, or revoked.",
                )
            else:
                # No token provided -> simple 401 without error code
                # This prevents mcp-remote from invalidating credentials
                await self._send_missing_token_error(send)
            return

        # Check required scopes
        auth_credentials = scope.get("auth")
        for required_scope in self.required_scopes:
            if auth_credentials is None or required_scope not in auth_credentials.scopes:
                await self._send_auth_error(
                    send,
                    status_code=403,
                    error="insufficient_scope",
                    description=f"Required scope: {required_scope}",
                )
                return

        await self.app(scope, receive, send)

    async def _send_missing_token_error(self, send: Send) -> None:
        """Send a 401 response for missing token WITHOUT invalid_token error.

        Per RFC 6750 Section 3, when the request lacks any authentication info,
        the resource server SHOULD NOT include an error code. It should include
        a WWW-Authenticate header pointing to where to get a token.

        This is crucial for mcp-remote compatibility because the SDK treats
        'invalid_token' as InvalidClientError which deletes client credentials.
        """
        # Build WWW-Authenticate header without error code
        www_auth_parts = ['realm="mcp"']
        if self.resource_metadata_url:
            www_auth_parts.append(f'resource_metadata="{self.resource_metadata_url}"')

        www_authenticate = f"Bearer {', '.join(www_auth_parts)}"

        # Response body
        body = {
            "error": "unauthorized",
            "error_description": (
                "Authentication required. Please authenticate to access this resource."
            ),
        }
        body_bytes = json.dumps(body).encode()

        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body_bytes)).encode()),
                    (b"www-authenticate", www_authenticate.encode()),
                ],
            }
        )

        await send(
            {
                "type": "http.response.body",
                "body": body_bytes,
            }
        )

        logger.debug("Auth error returned: missing_token (no Bearer token provided)")


def patch_fastmcp_auth_middleware():
    """Patch FastMCP's RequireAuthMiddleware to be RFC 6750 compliant.

    This function replaces FastMCP's RequireAuthMiddleware with our
    RFC6750CompliantAuthMiddleware. This must be called BEFORE creating
    any FastMCP servers.

    The patch is necessary because FastMCP's middleware returns 'invalid_token'
    error even when no token is provided, which causes mcp-remote to delete
    its client credentials.
    """
    import fastmcp.server.auth.middleware as fastmcp_middleware
    import fastmcp.server.http as fastmcp_http

    # Replace the class in both modules
    # Intentional monkey-patching for RFC 6750 compliance
    fastmcp_middleware.RequireAuthMiddleware = RFC6750CompliantAuthMiddleware  # type: ignore[assignment]
    fastmcp_http.RequireAuthMiddleware = RFC6750CompliantAuthMiddleware  # type: ignore[assignment]

    logger.debug("Patched FastMCP RequireAuthMiddleware for RFC 6750 compliance")


class OIDCProxyWithoutResource(OIDCProxy):
    """OIDC Proxy that filters the resource parameter for DCR compatibility.

    This enables support for IdPs that don't allow third-party apps to
    request API Resources without explicit permission grants (e.g., Logto).

    By filtering the resource parameter, we use OIDC only for authentication
    (ID token), not for API authorization. This enables DCR with mcp-remote
    and similar clients.

    Additionally, this class overrides get_middleware() to use RFC6750-compliant
    authentication middleware that properly distinguishes between "no token"
    and "invalid token" errors.
    """

    def get_middleware(self) -> list:
        """Get HTTP middleware with RFC 6750 compliant auth error handling.

        This overrides the parent's get_middleware() to use our custom
        RFC6750CompliantAuthMiddleware instead of the SDK's RequireAuthMiddleware.

        Returns
        -------
        list
            List of Starlette Middleware instances.
        """
        return [
            Middleware(
                AuthenticationMiddleware,  # type: ignore[arg-type]
                backend=BearerAuthBackend(self),
            ),
            Middleware(AuthContextMiddleware),  # type: ignore[arg-type]
        ]

    def _build_upstream_authorize_url(self, txn_id: str, transaction: dict[str, Any]) -> str:
        """Build authorize URL without the resource parameter.

        Parameters
        ----------
        txn_id : str
            The transaction ID for state tracking.
        transaction : dict
            The transaction data containing scopes and other params.

        Returns
        -------
        str
            The upstream authorization URL without resource parameter.
        """
        query_params: dict[str, Any] = {
            "response_type": "code",
            "client_id": self._upstream_client_id,
            "redirect_uri": f"{str(self.base_url).rstrip('/')}{self._redirect_path}",
            "state": txn_id,
        }

        scopes_to_use = transaction.get("scopes") or self.required_scopes or []
        if scopes_to_use:
            query_params["scope"] = " ".join(scopes_to_use)

        # Include PKCE challenge if present
        proxy_code_verifier = transaction.get("proxy_code_verifier")
        if proxy_code_verifier:
            challenge_bytes = hashlib.sha256(proxy_code_verifier.encode()).digest()
            proxy_code_challenge = urlsafe_b64encode(challenge_bytes).decode().rstrip("=")
            query_params["code_challenge"] = proxy_code_challenge
            query_params["code_challenge_method"] = "S256"

        # Filter out 'resource' parameter to avoid access_denied errors
        # from IdPs that don't support third-party resource requests
        if self._extra_authorize_params:
            extra_params = {
                k: v for k, v in self._extra_authorize_params.items() if k != "resource"
            }
            query_params.update(extra_params)

        separator = "&" if "?" in self._upstream_authorization_endpoint else "?"
        return f"{self._upstream_authorization_endpoint}{separator}{urlencode(query_params)}"


def configure_mcp_auth(
    oidc_well_known_endpoint: str,
    client_id: str,
    client_secret: str,
    mcp_base_url: str,
    scopes: list[str] | None = None,
):
    """Configure MCP authentication using mcpauth for multi-provider support.

    This function uses mcpauth to:
    1. Fetch OIDC provider configuration automatically
    2. Configure JWT token validation
    3. Generate RFC 9728 compliant resource metadata endpoints

    For providers that don't support DCR (like Logto for third-party apps),
    we use the OIDCProxyWithoutResource with resource parameter filtering.

    Parameters
    ----------
    oidc_well_known_endpoint : str
        The OIDC well-known configuration URL.
    client_id : str
        The OAuth client ID.
    client_secret : str
        The OAuth client secret.
    mcp_base_url : str
        The base URL for the MCP server.
    scopes : list[str], optional
        The OIDC scopes to request. Defaults to ["openid", "profile", "email"].

    Returns
    -------
    tuple
        A tuple of (auth, routes) where auth is the FastMCP auth provider and
        routes are the metadata routes to mount.
    """
    # Patch FastMCP's auth middleware to be RFC 6750 compliant
    # This must be done before creating any FastMCP servers
    patch_fastmcp_auth_middleware()

    if scopes is None:
        scopes = ["openid", "profile", "email"]

    # Extract issuer from well-known endpoint
    # e.g., "https://example.logto.app/oidc/.well-known/openid-configuration"
    #    -> "https://example.logto.app/oidc"
    issuer = oidc_well_known_endpoint.replace("/.well-known/openid-configuration", "")

    logger.info(f"Configuring MCP auth with issuer: {issuer}")

    # Fetch OIDC server configuration using mcpauth to validate the endpoint
    # This automatically handles different provider formats
    try:
        # We fetch the config to validate the OIDC endpoint is accessible,
        # but we don't use it directly since FastMCP's OIDCProxy handles OAuth
        _auth_server_config = fetch_server_config(issuer, AuthServerType.OIDC)
        logger.info(f"Fetched OIDC configuration from {issuer}")
    except Exception as e:
        logger.error(f"Failed to fetch OIDC configuration: {e}")
        raise

    # NOTE: We intentionally do NOT use mcpauth's resource_metadata_router() here.
    #
    # The problem: mcpauth generates routes for /.well-known/oauth-protected-resource/{path}
    # that point to the upstream IdP (e.g., Logto) as authorization_server.
    # But FastMCP's OIDCProxy acts as an OAuth proxy, so the authorization_server
    # should be the MCP server itself (e.g., http://localhost:5000/mcp/).
    #
    # mcp-remote behavior:
    # 1. Initial discovery: GET /.well-known/oauth-protected-resource/mcp/ (with slash)
    #    -> FastMCP route responds with authorization_servers: [mcp_base_url]
    # 2. finishAuth: GET /.well-known/oauth-protected-resource/mcp (no slash)
    #    -> mcpauth route responds with authorization_servers: [Logto URL]
    #
    # This mismatch causes mcp-remote to register with localhost but exchange tokens
    # with Logto, resulting in InvalidClientError and credential deletion.
    #
    # Solution: Only use FastMCP's well-known routes which correctly point to the
    # OAuth proxy endpoints on the MCP server itself.
    mcp_auth_routes = []
    logger.info("Skipping mcpauth resource metadata routes to avoid trailing slash inconsistency")

    # Create a TrustingUpstreamTokenVerifier for IdPs that return opaque tokens
    # (like Logto when no API Resource is requested).
    # This verifier accepts opaque tokens as valid because they were already
    # validated during the OAuth code exchange with the IdP.
    token_verifier = TrustingUpstreamTokenVerifier(
        client_id=client_id,
        client_secret=client_secret,
        required_scopes=scopes,
    )

    # Create OIDCProxy with resource parameter filtering for DCR compatibility
    # and the TrustingUpstreamTokenVerifier for opaque token support.
    # Note: required_scopes is not passed here because FastMCP doesn't allow it
    # when using a custom token_verifier. Scopes are configured on the verifier.
    auth = OIDCProxyWithoutResource(
        config_url=oidc_well_known_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        base_url=mcp_base_url,
        extra_authorize_params={"scope": " ".join(scopes)},
        token_verifier=token_verifier,
    )

    # Configure valid scopes for mcp-remote compatibility
    if auth.client_registration_options:
        auth.client_registration_options.valid_scopes = scopes

    # Get FastMCP's well-known routes for OAuth proxy
    well_known_routes = auth.get_well_known_routes(mcp_path="/")
    mcp_auth_routes.extend(well_known_routes)
    logger.info(f"Total auth routes: {len(mcp_auth_routes)}")

    return auth, mcp_auth_routes
