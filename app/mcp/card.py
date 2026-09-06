"""The server card: what this deployment says about its MCP endpoint.

SEP-2127 ("MCP Server Cards") describes a JSON document a server
publishes at a well-known path, so that clients and install choosers
learn where to connect and what the server is before any handshake.
The card is the base of the MCP Registry's ``server.json`` — which adds
``packages`` for local installs — so the same document serves both.

Two deliberate absences. No tool list: the SEP excludes it, and this
server regenerates its tools on every configuration reload, so a static
list would lie. No authentication hints: clients discover OAuth from the
401 challenge and the Protected Resource Metadata, as they do today.
"""

from __future__ import annotations

from importlib.metadata import version as package_version
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

# Where SEP-2127 puts the card. The SEP is still in review: if the path
# moves, this is the only place that knows it.
SERVER_CARD_PATH = "/.well-known/mcp-server-card"
SERVER_CARD_SCHEMA = "https://static.modelcontextprotocol.io/schemas/v1/server-card.schema.json"
# The MCP SDK exposes LATEST_PROTOCOL_VERSION but no list of the eras it
# still speaks, and FastMCP negotiates the best common one per
# connection. These two are the eras observed on the live deployment:
# 2026-07-28 from a FastMCP 4 client, 2025-11-25 from claude.ai.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("2026-07-28", "2025-11-25")
REPOSITORY = {"url": "https://github.com/geobeyond/fastgeoapi", "source": "github"}
# The second half of the name: the server software, whatever the host.
SERVER_SLUG = "fastgeoapi"


def _is_ip(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def default_server_name(base_url: str) -> str:
    """Derive the reverse-DNS card name from the deployment's public URL.

    ``https://fastgeoapi.fly.dev`` becomes ``dev.fly.fastgeoapi/fastgeoapi``.
    An IP address or a missing host is not a name, so those fall back to
    the ``localhost`` namespace — the development case.
    """
    host = (urlsplit(base_url).hostname or "").strip(".").lower()
    if not host or _is_ip(host):
        host = "localhost"
    namespace = ".".join(reversed(host.split(".")))
    return f"{namespace}/{SERVER_SLUG}"


def validate_server_name(name: str) -> str:
    """Enforce the SEP's rule: a reverse-DNS namespace, exactly one slash."""
    parts = name.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            f"invalid MCP server card name {name!r}: SEP-2127 requires "
            "'<reverse-dns-namespace>/<server-name>' with exactly one slash"
        )
    return name


def build_server_card(
    openapi: dict[str, Any],
    *,
    base_url: str,
    context: str,
    name: str | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Build the card from the current OpenAPI document.

    Parameters
    ----------
    openapi
        The document pygeoapi generated for the running configuration.
        Its ``info`` block already carries title and description resolved
        in the server's default language, which is why the card reads
        them here rather than from the raw, multilingual configuration.
    base_url
        The public origin of the deployment; a trailing slash is ignored.
    context
        The path pygeoapi is mounted at (``FASTGEOAPI_CONTEXT``).
    name
        An explicit reverse-DNS name. Derived from ``base_url`` when None.
    version
        Overrides the installed fastgeoapi version.

    Returns
    -------
        The card, as SEP-2127 defines it — and nothing it does not.
    """
    base = base_url.rstrip("/")
    info = openapi.get("info", {})
    return {
        "$schema": SERVER_CARD_SCHEMA,
        "name": validate_server_name(name or default_server_name(base)),
        "version": version or package_version("fastgeoapi"),
        "title": info.get("title", SERVER_SLUG),
        "description": info.get("description", ""),
        "websiteUrl": f"{base}{context}",
        "repository": dict(REPOSITORY),
        "remotes": [
            {
                "type": "streamable-http",
                "url": f"{base}/mcp/",
                "supportedProtocolVersions": list(SUPPORTED_PROTOCOL_VERSIONS),
            }
        ],
    }


class ServerCard:
    """The card of the running deployment, rebuilt when the configuration reloads.

    Holds what does not change across reloads — where the deployment is
    reachable, its context, the operator's name for it — and rebuilds
    the document from each new OpenAPI. Reading ``current`` is a plain
    attribute access, so a request never waits on a reload.
    """

    def __init__(
        self,
        openapi: dict[str, Any],
        *,
        base_url: str,
        context: str,
        name: str | None = None,
    ) -> None:
        self._base_url = base_url
        self._context = context
        self._name = name
        self.current: dict[str, Any] = build_server_card(
            openapi, base_url=base_url, context=context, name=name
        )

    def update(self, openapi: dict[str, Any]) -> None:
        """Rebuild the card from a freshly generated OpenAPI document."""
        self.current = build_server_card(
            openapi, base_url=self._base_url, context=self._context, name=self._name
        )


def server_card_route(card: ServerCard) -> Route:
    """The public GET route for the card, with the headers SEP-2127 asks for."""

    async def endpoint(request: Request) -> JSONResponse:
        return JSONResponse(
            card.current,
            headers={
                # The install chooser reads the card from the browser,
                # cross-origin. The app's CORS middleware only answers
                # requests that carry an Origin; the SEP wants the header
                # unconditionally, so it is set here.
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET",
                "Cache-Control": "public, max-age=3600",
            },
        )

    return Route(SERVER_CARD_PATH, endpoint, methods=["GET"])
