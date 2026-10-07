"""MCP Authentication Provider built on fastmcp's OIDCProxy.

This module provides a provider-agnostic authentication setup for MCP
servers: fastmcp's OIDCProxy handles OIDC discovery, DCR, PKCE and token
proxying against any OIDC-compliant identity provider (Logto, Auth0,
Keycloak, etc.) without custom per-provider code.
"""

import base64
import json
import logging
from collections.abc import Callable
from urllib.parse import parse_qsl

from fastmcp.server.auth.oidc_proxy import OIDCProxy
from loguru import logger
from mcp.server.auth.provider import AccessToken
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class MCPAuthMisconfiguredError(RuntimeError):
    """MCP is enabled but no authentication is configured.

    Raised at startup (fail-closed by design): booting the MCP server
    with ``auth=None`` exposes every generated tool unauthenticated,
    and the MCP-to-pygeoapi hop targets the raw sub-app with no
    middleware — so the whole API would leak through MCP even when
    the regular HTTP surface is protected. The only way to run MCP
    without authentication is the explicit first-class passthrough
    opt-in ``FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED=true``.
    """


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


def _coerce_consent_mode(consent_mode: str | None) -> bool | str:
    """Map a human-friendly consent string to FastMCP's expected value.

    FastMCP's ``OAuthProxy`` accepts ``require_authorization_consent`` as
    ``bool | Literal["remember", "external"]``. This helper translates the
    ``FASTGEOAPI_MCP_CONSENT_MODE`` env value into that type.

    Parameters
    ----------
    consent_mode : str | None
        One of ``"always"``, ``"remember"``, ``"external"``, ``"never"``
        (case-insensitive). ``None`` or unknown values fall back to
        ``"remember"``.

    Returns
    -------
    bool | str
        ``True`` for ``"always"``, ``False`` for ``"never"``, or the literal
        string for ``"remember"`` / ``"external"``.
    """
    mapping: dict[str, bool | str] = {
        "always": True,
        "remember": "remember",
        "external": "external",
        "never": False,
    }
    if consent_mode is None:
        return "remember"
    resolved = mapping.get(consent_mode.strip().lower())
    if resolved is None:
        logger.warning(
            f"Unknown FASTGEOAPI_MCP_CONSENT_MODE '{consent_mode}'; falling back to 'remember'"
        )
        return "remember"
    return resolved


DEFAULT_MCP_ACCESS_TOKEN_EXPIRY_SECONDS = 60 * 60 * 24  # 24 hours

CLIENT_ASSERTION_SIGNING_ALGS = ["RS256"]
"""The algorithms fastmcp verifies a ``private_key_jwt`` client assertion with.

Its JWT verifier's default, so the key a client signs with must be an RSA key.
"""


class _SigningAlgsMetadata:
    """The authorization server metadata, with the algorithms of ``private_key_jwt``.

    RFC 8414 §2 asks for ``token_endpoint_auth_signing_alg_values_supported``
    wherever ``private_key_jwt`` is offered, and fastmcp leaves it out: a
    client whose JWKS holds keys of several types can only guess which one
    to sign with. Pure ASGI, around the CORS app fastmcp mounts; a value
    fastmcp publishes itself is kept.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Answer as fastmcp does, adding the algorithms to the document of a GET."""
        if scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        start: Message = {}
        body = bytearray()

        async def held(message: Message) -> None:
            if message["type"] == "http.response.start":
                start.update(message)
                return
            if message["type"] != "http.response.body":
                await send(message)
                return
            body.extend(message.get("body", b""))
            if message.get("more_body", False):
                return
            content = _with_signing_algs(bytes(body)) if start["status"] == 200 else bytes(body)
            headers = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
            headers.append((b"content-length", str(len(content)).encode()))
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": content})

        await self.app(scope, receive, held)


def _with_signing_algs(body: bytes) -> bytes:
    """``body`` with the signing algorithms, when it offers ``private_key_jwt``."""
    metadata = json.loads(body)
    if "private_key_jwt" not in (metadata.get("token_endpoint_auth_methods_supported") or []):
        return body
    metadata.setdefault(
        "token_endpoint_auth_signing_alg_values_supported", CLIENT_ASSERTION_SIGNING_ALGS
    )
    return json.dumps(metadata, separators=(",", ":")).encode()


_REFUSAL_LOGGER = "fastmcp.server.auth.providers.jwt"
"""fastmcp's JWT verifier, which says why it refuses a client assertion at DEBUG only."""

_REFUSALS = (
    "Token validation failed",
    "JWKS key lookup failed",
    "Skipping JWKS key",
    "Skipping unusable JWKS key",
    "JWKS fetch blocked",
    "JWKS key processing failed",
)
"""The DEBUG messages of that verifier that say why an assertion was refused."""


class _RefusalsOnly(logging.Filter):
    """At DEBUG, only the reasons for a refusal, escaped and bounded with ``_safe``.

    A reason can carry what the client sent, such as a kid. fastmcp's other
    DEBUG messages name users and successful exchanges the logs need not keep.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno > logging.DEBUG:
            return True
        message = record.getMessage()
        if not message.startswith(_REFUSALS):
            return False
        record.msg, record.args = _safe(message), ()
        return True


class _RefusedTokenLog:
    """A log line for each refused token request, around the CORS app fastmcp mounts.

    fastmcp tells the client why it refused a token and logs little of it,
    so a partner's 401 cannot be read on this side. The line names the
    grant, the client and the answer, and for a client assertion or an
    ID-JAG its header and claims: never the assertion, the code or a secret.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Hand the request to fastmcp unchanged, and log its answer when it refuses."""
        if scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            body.extend(message.get("body", b""))
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        form = bytes(body)
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if replayed:
                return await receive()
            replayed = True
            return {"type": "http.request", "body": form, "more_body": False}

        status = 0
        answer = bytearray()

        async def watch(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and status >= 400:
                answer.extend(message.get("body", b""))
                if not message.get("more_body", False):
                    _log_refused(status, form, bytes(answer))
            await send(message)

        await self.app(scope, replay, watch)


def _log_refused(status: int, form: bytes, answer: bytes) -> None:
    """One line on a refused token request: the grant, the client, the error, the assertion."""
    fields = dict(parse_qsl(form.decode("utf-8", "replace")))
    try:
        reply = json.loads(answer)
    except ValueError:
        reply = None
    if not isinstance(reply, dict):
        reply = {}
    parts = [
        f"status={status}",
        f"grant_type={_safe(fields.get('grant_type'))}",
        f"client_id={_safe(fields.get('client_id'))}",
        f"error={_safe(reply.get('error'))}",
        f"error_description={_safe(reply.get('error_description'))}",
    ]
    assertion = fields.get("client_assertion") or fields.get("assertion")
    if assertion:
        parts.append(_described(assertion))
    logger.warning(f"MCP token request refused: {' '.join(parts)}")


_LOGGED_LENGTH = 200
"""The most characters a refused token request writes to the log for one value."""


def _safe(value: object) -> str:
    """``value`` for a log line, its control characters escaped and its length bounded.

    Anyone can send a token request, and a line break in a form field or a
    claim would otherwise write records of its own into the log.
    """
    text = "".join(
        character if character.isprintable() else character.encode("unicode_escape").decode()
        for character in str(value)
    )
    return text if len(text) <= _LOGGED_LENGTH else f"{text[:_LOGGED_LENGTH]}…"


def _described(assertion: str) -> str:
    """The header and claims of an assertion, its signature left out.

    ``sub`` is written out when it repeats ``iss``, as in a client
    assertion where both are the client id; in an ID-JAG it is the user,
    and only its presence is said.
    """
    try:
        header_part, claims_part = assertion.split(".")[:2]
        header = json.loads(_decoded(header_part))
        claims = json.loads(_decoded(claims_part))
    except (ValueError, RecursionError):
        # json raises RecursionError on a part nested past the recursion
        # limit: that part is unreadable too.
        return "assertion=unreadable"
    if not isinstance(header, dict) or not isinstance(claims, dict):
        return "assertion=unreadable"
    subject = claims.get("sub")
    described = [f"{key}={_safe(header.get(key))}" for key in ("alg", "kid", "typ")]
    described += [f"{key}={_safe(claims.get(key))}" for key in ("iss", "aud", "iat", "exp")]
    shown = _safe(subject) if subject == claims.get("iss") else "present" if subject else "absent"
    described.append(f"sub={shown}")
    described.append(f"jti={'present' if claims.get('jti') else 'absent'}")
    return " ".join(described)


def _decoded(part: str) -> bytes:
    """A base64url part of a JWT, its padding restored."""
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _wrapped(route: Route, wrapper: Callable[[ASGIApp], ASGIApp]) -> Route:
    """``route`` with its endpoint inside ``wrapper``."""
    return Route(
        route.path,
        endpoint=wrapper(route.endpoint),
        methods=route.methods,
        name=route.name,
        include_in_schema=route.include_in_schema,
    )


class _InteropOIDCProxy(OIDCProxy):
    """fastmcp's OIDC proxy, readable by the clients and the logs on the other side.

    Its metadata names the algorithms of client assertions, and each token
    request it refuses leaves a line in the log.
    """

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """Fastmcp's routes, the server metadata and the token endpoint wrapped."""
        routes = []
        for route in super().get_routes(mcp_path):
            if route.path.startswith("/.well-known/oauth-authorization-server"):
                route = _wrapped(route, _SigningAlgsMetadata)
            elif route.path == "/token":
                route = _wrapped(route, _RefusedTokenLog)
            routes.append(route)
        return routes


def configure_mcp_auth(
    oidc_well_known_endpoint: str,
    client_id: str,
    client_secret: str,
    mcp_base_url: str,
    scopes: list[str] | None = None,
    consent_mode: str | None = "remember",
    access_token_expiry_seconds: int | None = None,
    trusted_issuers: list[str] | None = None,
):
    """Configure MCP authentication via fastmcp's OIDCProxy.

    This function:
    1. Fetch OIDC provider configuration automatically
    2. Configure JWT token validation
    3. Generate RFC 9728 compliant resource metadata endpoints

    For providers that don't support DCR (like Logto for third-party apps),
    the proxy is configured with `forward_resource=False`.

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
        The OIDC scopes to request. Defaults to
        ["openid", "profile", "email", "offline_access"]. ``offline_access``
        is required for the IdP to issue a refresh token; without it the MCP
        client must re-run the full authorization on every access-token expiry
        instead of refreshing silently.
    consent_mode : str | None, optional
        Consent screen behavior. One of ``"always"``, ``"remember"``,
        ``"external"``, ``"never"`` (see :func:`_coerce_consent_mode`).
        Defaults to ``"remember"``: the approval page is shown the first
        time and then silently approved on return visits (the approval is
        persisted in a host-scoped, HMAC-signed browser cookie, so it
        survives server deploys). This stops the approval page from
        reappearing on every fresh authorization while keeping the
        first-time consent and its CSRF double-submit protection.
    access_token_expiry_seconds : int | None, optional
        Lifetime of the access token the proxy issues to MCP clients,
        decoupled from the upstream IdP ``expires_in``. Defaults to 24
        hours. This is safe because the FastMCP JWT is a reference token:
        every request re-validates the upstream token (with transparent
        refresh when expired), so a revoked or expired upstream session
        still fails immediately. A value of ``0`` (or negative) opts out
        and mirrors the upstream ``expires_in`` on the client-facing JWT.
        Longer client TTLs matter for clients like mcp-remote that keep
        tokens only in process memory and renew via refresh grant.

    Returns
    -------
    tuple
        A tuple of (auth, routes) where auth is the FastMCP auth provider and
        routes are the metadata routes to mount.
    """
    if scopes is None:
        scopes = ["openid", "profile", "email", "offline_access"]

    # Extract issuer from well-known endpoint
    # e.g., "https://example.logto.app/oidc/.well-known/openid-configuration"
    #    -> "https://example.logto.app/oidc"
    issuer = oidc_well_known_endpoint.replace("/.well-known/openid-configuration", "")

    logger.info(f"Configuring MCP auth with issuer: {issuer}")

    # NOTE: Only fastmcp's own well-known routes are mounted here. An
    # external resource-metadata router (mcpauth's, removed 2026-08-01)
    # used to advertise the upstream IdP as authorization_server, while
    # the OIDCProxy needs the MCP server itself to be advertised
    # (e.g., http://localhost:5000/mcp/).
    #
    # mcp-remote behavior:
    # 1. Initial discovery: GET /.well-known/oauth-protected-resource/mcp/ (with slash)
    #    -> FastMCP route responds with authorization_servers: [mcp_base_url]
    # 2. finishAuth: GET /.well-known/oauth-protected-resource/mcp (no slash)
    #    -> the external route responded with authorization_servers: [Logto URL]
    #
    # This mismatch causes mcp-remote to register with localhost but exchange tokens
    # with Logto, resulting in InvalidClientError and credential deletion.
    #
    # Solution: Only use FastMCP's well-known routes which correctly point to the
    # OAuth proxy endpoints on the MCP server itself.
    mcp_auth_routes = []
    logger.info("Using only fastmcp well-known routes (single source for RFC 9728 metadata)")

    # Create a TrustingUpstreamTokenVerifier for IdPs that return opaque tokens
    # (like Logto when no API Resource is requested).
    # This verifier accepts opaque tokens as valid because they were already
    # validated during the OAuth code exchange with the IdP.
    # What we REQUEST upstream and what we REQUIRE on an inbound token are
    # different things. `offline_access` is a request-time scope that asks
    # the IdP for a refresh token; demanding it back on every access token
    # would reject perfectly valid ones — in particular EMA tokens, which
    # by design carry no refresh (the client re-exchanges its assertion).
    # `openid` is the one scope that must actually be present.
    token_verifier = TrustingUpstreamTokenVerifier(
        client_id=client_id,
        client_secret=client_secret,
        required_scopes=[scope for scope in scopes if scope == "openid"],
    )

    # Create the OIDC proxy. `forward_resource=False` makes fastmcp skip the
    # `resource` parameter on the upstream `/authorize` URL — necessary for
    # IdPs like Logto that reject third-party resource indicators.
    # Note: required_scopes is not passed here because FastMCP doesn't allow it
    # when using a custom token_verifier. Scopes are configured on the verifier.
    if access_token_expiry_seconds is None:
        access_token_expiry_seconds = DEFAULT_MCP_ACCESS_TOKEN_EXPIRY_SECONDS
    client_token_ttl = access_token_expiry_seconds if access_token_expiry_seconds > 0 else None

    # Enterprise-Managed Authorization (SEP-990): with trusted issuers
    # configured, the token endpoint also accepts an ID-JAG — an assertion
    # the enterprise IdP mints for an employee — and exchanges it for an
    # access token, no browser and no per-user consent. Left unset the
    # grant answers `unsupported_grant_type`, so the surface only exists
    # for operators who named the identity providers they trust.
    identity_assertion = None
    if trusted_issuers:
        from fastmcp.server.auth import IdentityAssertion

        identity_assertion = IdentityAssertion(trusted_issuers=list(trusted_issuers))

    # fastmcp says why it refuses a client assertion at DEBUG only: the reason
    # for a partner's 401 reaches the logs, and nothing else at that level.
    refusals = logging.getLogger(_REFUSAL_LOGGER)
    refusals.setLevel(logging.DEBUG)
    if not any(isinstance(each, _RefusalsOnly) for each in refusals.filters):
        refusals.addFilter(_RefusalsOnly())

    auth = _InteropOIDCProxy(
        identity_assertion=identity_assertion,
        config_url=oidc_well_known_endpoint,
        client_id=client_id,
        client_secret=client_secret,
        base_url=mcp_base_url,
        extra_authorize_params={"scope": " ".join(scopes)},
        token_verifier=token_verifier,
        forward_resource=False,
        require_authorization_consent=_coerce_consent_mode(consent_mode),
        fastmcp_access_token_expiry_seconds=client_token_ttl,
    )
    logger.info(f"MCP consent mode: {consent_mode or 'remember'}")
    logger.info(
        "MCP identity assertion (EMA): "
        f"{f'enabled for {len(trusted_issuers)} issuer(s)' if trusted_issuers else 'disabled'}"
    )
    logger.info(
        "MCP client access-token TTL: "
        f"{f'{client_token_ttl}s' if client_token_ttl else 'mirror upstream expires_in'}"
    )

    # Scopes a client may REQUEST (distinct from the scopes we require back
    # on a token, above). This must include the full set — `offline_access`
    # included — because it is also the fallback for clients that identify
    # by URL without declaring scopes: Claude's CIMD document has no `scope`
    # field, so its synthetic client inherits this default, and requesting
    # `offline_access` against a narrower default is rejected as
    # `invalid_scope` before the user ever sees a login screen.
    # `update_default_scopes` is the upstream API that keeps every derived
    # place in sync (DCR registration options *and* the CIMD manager);
    # setting `valid_scopes` alone left the CIMD path behind.
    auth.update_default_scopes(scopes)

    # Get FastMCP's well-known routes for OAuth proxy
    well_known_routes = auth.get_well_known_routes(mcp_path="/")
    mcp_auth_routes.extend(well_known_routes)
    logger.info(f"Total auth routes: {len(mcp_auth_routes)}")

    return auth, mcp_auth_routes
