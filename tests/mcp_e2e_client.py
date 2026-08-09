"""Reusable MCP client harness for end-to-end tests.

The OAuth dance in :mod:`tests.test_mcp_oauth_e2e` asserts every hop of
the protocol by hand — that is its job. This module wraps the same dance
as a *client*: something a test can call to obtain an authenticated
``fastmcp.Client`` talking real Streamable HTTP to a running fastgeoapi
instance, then exercise tools the way an AI agent would.

It exists for two reasons:

1. **Interop-shaped tests.** The OpenID AIIM interoperability program
   tests an MCP server through a client that performs discovery, obtains
   a token from the advertised authorization server, and calls tools.
   That is exactly what :func:`authenticated_mcp_client` does, so the
   same code path we ask partners to run is covered by our own suite.
2. **CIMD.** URL-identified clients (Client ID Metadata Documents)
   differ from DCR clients only in how the client is identified; the
   rest of the dance is shared. Keeping the dance in one place lets the
   CIMD tests reuse it with a different registration step.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import httpx

# A redirect target that is never fetched: the harness reads the code out
# of the Location header instead of running a callback server.
CLIENT_REDIRECT_URI = "http://localhost:1/cb"

DEFAULT_SCOPE = "openid profile email"


def pkce_pair() -> tuple[str, str]:
    """Return a ``(code_verifier, code_challenge)`` pair for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _describe_html_error(body: str) -> str:
    """Extract title and first paragraph from a fastmcp OAuth error page.

    Those pages bury the real message under ~2KB of inline CSS; surfacing
    ``<title>`` and the first ``<p>`` keeps CI failures readable.
    """
    title = re.search(r"<title>([^<]+)</title>", body)
    message = re.search(r"<p>([^<]+)</p>", body)
    return " — ".join(m.group(1).strip() for m in (title, message) if m)


def follow_until(
    client: httpx.Client,
    response: httpx.Response,
    stop_prefix: str,
    max_hops: int = 12,
) -> httpx.Response:
    """Step through redirects until the next ``Location`` hits ``stop_prefix``.

    Returns the response whose ``Location`` points at ``stop_prefix``.
    Uses the caller's client so cookies persist across hops.
    """
    for _ in range(max_hops):
        if response.status_code not in (301, 302, 303, 307, 308):
            detail = _describe_html_error(response.text)
            raise AssertionError(
                f"Expected redirect, got {response.status_code}: {detail or response.text[:300]}"
            )
        location = response.headers.get("location", "")
        if not location:
            raise AssertionError("Redirect missing Location header")
        next_url = str(httpx.URL(str(response.url)).join(location))
        if next_url.startswith(stop_prefix):
            return response
        response = client.get(next_url, follow_redirects=False)
    raise AssertionError(f"Too many redirects before reaching {stop_prefix}")


def is_consent_form(response: httpx.Response) -> bool:
    """True when the response is fastmcp's consent interstitial."""
    return response.status_code == 200 and 'name="txn_id"' in response.text


def submit_consent_form(
    http: httpx.Client, form: httpx.Response, consent_url: str
) -> httpx.Response:
    """Approve a fastmcp consent form, honouring its CSRF double-submit."""
    csrf = re.search(r'name="csrf_token"\s+value="([^"]+)"', form.text)
    txn = re.search(r'name="txn_id"\s+value="([^"]+)"', form.text)
    assert csrf and txn, "consent form missing csrf_token/txn_id"
    return http.post(
        consent_url,
        data={"txn_id": txn.group(1), "action": "approve", "csrf_token": csrf.group(1)},
        follow_redirects=False,
    )


@contextmanager
def headless_browser(monkeypatch, max_hops: int = 20):
    """Stand in for the browser fastmcp's OAuth client tries to open.

    ``OAuth.redirect_handler`` calls ``webbrowser.open(url)`` directly —
    there is no injectable hook — so the seam is the module-level import.
    The walk runs on a **thread**: ``webbrowser.open`` is called from
    async code without being awaited, and the OAuth callback server lives
    in that same event loop, so doing blocking HTTP inline would deadlock
    the flow it is supposed to complete.

    Yields the list of exceptions raised inside the thread. Failures there
    surface as a callback timeout, several seconds and one unhelpful
    message later, so tests should assert the list is empty and get the
    real cause instead.
    """
    import threading
    import webbrowser

    errors: list[Exception] = []
    threads: list[threading.Thread] = []

    def walk(url: str) -> None:
        try:
            with httpx.Client(timeout=15.0, follow_redirects=False) as http:
                response = http.get(url)
                for _ in range(max_hops):
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location", "")
                        if not location:
                            raise AssertionError(f"redirect without Location from {response.url}")
                        response = http.get(str(httpx.URL(str(response.url)).join(location)))
                    elif is_consent_form(response):
                        origin = httpx.URL(str(response.url))
                        consent_url = str(origin.copy_with(query=None, path="/mcp/consent"))
                        response = submit_consent_form(http, response, consent_url)
                    else:
                        return
                raise AssertionError(f"too many hops, stuck at {response.url}")
        except Exception as exc:
            errors.append(exc)

    def fake_open(url: str, *_args, **_kwargs) -> bool:
        thread = threading.Thread(target=walk, args=(url,), daemon=True)
        thread.start()
        threads.append(thread)
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)
    try:
        yield errors
    finally:
        for thread in threads:
            thread.join(timeout=15)


@dataclass
class MCPOAuthClient:
    """Drives the OAuth authorization-code dance against an MCP server.

    Parameters
    ----------
    base_url:
        Base URL of the running fastgeoapi instance.
    client_id:
        Pre-existing client identifier. Leave unset to register through
        DCR; set it to a metadata-document URL for CIMD flows.
    """

    base_url: str
    client_id: str | None = None
    scope: str = DEFAULT_SCOPE
    redirect_uri: str = CLIENT_REDIRECT_URI
    access_token: str | None = field(default=None, init=False)
    refresh_token: str | None = field(default=None, init=False)

    def register_via_dcr(self, http: httpx.Client, client_name: str = "fastgeoapi e2e") -> str:
        """Register a public client (RFC 7591) and store its identifier."""
        response = http.post(
            f"{self.base_url}/mcp/register",
            json={
                "redirect_uris": [self.redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": self.scope,
                "token_endpoint_auth_method": "none",
                "client_name": client_name,
            },
        )
        assert response.status_code in (200, 201), response.text
        self.client_id = response.json()["client_id"]
        return self.client_id

    def authorize(self, http: httpx.Client, code_challenge: str, state: str) -> str:
        """Walk /authorize, the consent interstitial and the IdP hops.

        Returns the authorization code handed back to the client redirect.
        The upstream IdP must already have the user logged in and
        consented (see pytest-iam's ``login()`` / ``consent()``).
        """
        assert self.client_id, "register_via_dcr() or an explicit client_id is required"

        response = http.get(
            f"{self.base_url}/mcp/authorize",
            params={
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": self.scope,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert response.status_code in (302, 303, 307), response.text[:300]
        location = response.headers["location"]

        # The consent interstitial is optional: it only appears in
        # "remember"/"always" consent modes.
        if "/consent?txn_id=" in location:
            response = self._approve_consent(http, response, location)
            location = response.headers["location"]

        upstream = str(httpx.URL(str(response.url)).join(location))
        response = http.get(upstream, follow_redirects=False)
        callback = follow_until(http, response, f"{self.base_url}/mcp/auth/callback")
        callback_url = str(httpx.URL(str(callback.url)).join(callback.headers["location"]))

        response = http.get(callback_url, follow_redirects=False)
        final = follow_until(http, response, self.redirect_uri)
        final_url = str(httpx.URL(str(final.url)).join(final.headers["location"]))
        params = parse_qs(urlparse(final_url).query)
        assert params.get("state") == [state], final_url
        assert "code" in params, final_url
        return params["code"][0]

    def _approve_consent(
        self, http: httpx.Client, response: httpx.Response, location: str
    ) -> httpx.Response:
        """Submit the fastmcp consent form, honouring its CSRF double-submit."""
        form = http.get(str(httpx.URL(str(response.url)).join(location)), follow_redirects=False)
        assert form.status_code == 200, form.text[:300]
        approved = submit_consent_form(http, form, f"{self.base_url}/mcp/consent")
        assert approved.status_code in (302, 303), approved.text[:300]
        return approved

    def exchange_code(self, http: httpx.Client, code: str, code_verifier: str) -> str:
        """Exchange the authorization code for tokens (public client, PKCE)."""
        response = http.post(
            f"{self.base_url}/mcp/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "code_verifier": code_verifier,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("token_type", "").lower() == "bearer", body
        self.access_token = body["access_token"]
        self.refresh_token = body.get("refresh_token")
        return self.access_token

    def refresh(self, http: httpx.Client) -> httpx.Response:
        """Redeem the stored refresh token for a fresh access token.

        Returns the raw response so callers can assert on the whole body
        (``expires_in``, refresh-token rotation) and not just the happy
        path. On success the stored tokens are replaced.
        """
        assert self.refresh_token, "no refresh token: the IdP issued none"
        response = http.post(
            f"{self.base_url}/mcp/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
            },
        )
        if response.status_code == 200:
            body = response.json()
            self.access_token = body["access_token"]
            # Rotation is one-time-use: keeping the old value would make
            # the next refresh fail in a way that looks like a server bug.
            self.refresh_token = body.get("refresh_token", self.refresh_token)
        return response

    def run_dance(self, http: httpx.Client | None = None) -> str:
        """Run the whole dance (DCR when needed) and return the access token."""
        owns_client = http is None
        http = http or httpx.Client(timeout=10.0)
        try:
            if self.client_id is None:
                self.register_via_dcr(http)
            verifier, challenge = pkce_pair()
            code = self.authorize(http, challenge, secrets.token_urlsafe(16))
            return self.exchange_code(http, code, verifier)
        finally:
            if owns_client:
                http.close()


@asynccontextmanager
async def authenticated_mcp_client(base_url: str, oauth: MCPOAuthClient | None = None):
    """Yield an authenticated ``fastmcp.Client`` over Streamable HTTP.

    Runs the OAuth dance (unless ``oauth`` already holds a token), then
    connects a real MCP client to ``<base_url>/mcp/`` with the resulting
    bearer token — the same path an MCP client takes in an interop test.
    """
    from fastmcp import Client
    from fastmcp.client.auth import BearerAuth
    from fastmcp.client.transports import StreamableHttpTransport

    oauth = oauth or MCPOAuthClient(base_url=base_url)
    token = oauth.access_token or oauth.run_dance()

    transport = StreamableHttpTransport(url=f"{base_url}/mcp/", auth=BearerAuth(token))
    async with Client(transport) as client:
        yield client
