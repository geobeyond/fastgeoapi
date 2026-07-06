# MCP Server (Model Context Protocol)

fastgeoapi includes an optional integrated MCP server that exposes OGC API endpoints as tools for AI assistants and LLM-based applications. The MCP server is built using [FastMCP](https://github.com/jlowin/fastmcp) and automatically generates tools from the pygeoapi OpenAPI specification.

## What is MCP?

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) is an open standard that enables AI assistants to interact with external tools and data sources. By implementing an MCP server, fastgeoapi allows AI assistants like Claude Desktop to:

- Query geospatial feature collections
- Retrieve metadata about available datasets
- Execute OGC API processes
- Access conformance information

## Features

| Feature                         | Description                                                                            |
| ------------------------------- | -------------------------------------------------------------------------------------- |
| **Automatic Tool Generation**   | Tools are generated from the OGC API OpenAPI spec                                      |
| **OAuth Authentication**        | Supports OIDC authentication with any OAuth provider                                   |
| **RFC 9728 Compliant**          | Implements OAuth 2.0 Protected Resource Metadata                                       |
| **Dynamic Client Registration** | Compatible with mcp-remote and other MCP clients                                       |
| **Provider Agnostic**           | Uses [mcpauth](https://github.com/alonsosilvaallende/mcpauth) for multi-IdP support    |
| **Stateless Streamable HTTP**   | Single-endpoint transport; every request is self-contained (suspend/redeploy friendly) |

## Enable the MCP Server

To enable the MCP server, set the `FASTGEOAPI_WITH_MCP` environment variable in your `.env` file:

```shell
# For development
DEV_FASTGEOAPI_WITH_MCP=true

# For production
PROD_FASTGEOAPI_WITH_MCP=true
```

The MCP server will be mounted at the `/mcp` endpoint.

## Configuration

### Basic Configuration (No Authentication)

For development or internal use without authentication:

```shell
# .env file
ENV_STATE=dev

# Server configuration
HOST=0.0.0.0
PORT=5000

# Enable MCP
DEV_FASTGEOAPI_WITH_MCP=true

# Pygeoapi configuration
DEV_PYGEOAPI_CONFIG=pygeoapi-config.yml
DEV_PYGEOAPI_OPENAPI=pygeoapi-openapi.yml
DEV_PYGEOAPI_BASEURL=http://localhost:5000
DEV_FASTGEOAPI_CONTEXT=/geoapi

# Disable authentication
DEV_API_KEY_ENABLED=false
DEV_JWKS_ENABLED=false
DEV_OPA_ENABLED=false
```

### With OAuth Authentication

To enable OAuth authentication for the MCP server, configure JWKS with your OIDC provider:

```shell
# .env file
ENV_STATE=dev

# Server configuration
HOST=0.0.0.0
PORT=5000

# Enable MCP with OAuth
DEV_FASTGEOAPI_WITH_MCP=true
DEV_JWKS_ENABLED=true

# OIDC Configuration
DEV_OIDC_WELL_KNOWN_ENDPOINT=https://your-idp.example.com/.well-known/openid-configuration
DEV_OIDC_CLIENT_ID=your-client-id
DEV_OIDC_CLIENT_SECRET=your-client-secret

# Pygeoapi configuration
DEV_PYGEOAPI_CONFIG=pygeoapi-config.yml
DEV_PYGEOAPI_OPENAPI=pygeoapi-openapi.yml
DEV_PYGEOAPI_BASEURL=http://localhost:5000
DEV_FASTGEOAPI_CONTEXT=/geoapi

# Disable other auth methods
DEV_API_KEY_ENABLED=false
DEV_OPA_ENABLED=false
```

### Consent Mode (`FASTGEOAPI_MCP_CONSENT_MODE`)

When OAuth is enabled, the MCP server acts as an OAuth proxy and can present a
**consent (authorization approval) screen** before redirecting the user to the
upstream Identity Provider. `FASTGEOAPI_MCP_CONSENT_MODE` controls that
behaviour. It is read **only when `FASTGEOAPI_WITH_MCP=true`** and an OIDC
provider is configured; otherwise it is ignored.

```shell
# .env file — optional, defaults to "remember" when unset
DEV_FASTGEOAPI_MCP_CONSENT_MODE=remember
```

| Value      | Consent screen                                 | Consent binding cookie check | When to use                                                                 |
| ---------- | ---------------------------------------------- | ---------------------------- | --------------------------------------------------------------------------- |
| `always`   | Shown on **every** authorization               | Enforced                     | Strongest protection; re-prompts the user on each fresh authorization       |
| `remember` | Shown once per browser, then silently approved | Enforced                     | **Default.** Balances UX and protection for multi-user / shared deployments |
| `external` | Skipped (consent handled outside fastgeoapi)   | Skipped                      | You manage consent in a separate layer                                      |
| `never`    | Skipped entirely                               | **Skipped**                  | Single-tenant / single trusted user (see risks below)                       |

Unknown or unset values fall back to `remember`.

#### Why the consent binding cookie matters

In `always` and `remember` modes the proxy issues a signed **consent binding
cookie** to the browser that approved consent and re-verifies it on the IdP
callback. This is a [confused-deputy](https://en.wikipedia.org/wiki/Confused_deputy_problem)
protection: a victim lured to a crafted authorization URL won't hold the
matching cookie and is rejected.

The trade-off is fragility on **re-authorization**: the cookie must survive the
cross-site redirect back from the IdP. In some scenarios — a long machine
suspend (e.g. Fly.io auto-suspend), `SameSite` handling, or concurrent OAuth
flows opened by the client — the cookie does not round-trip, and the callback
fails with:

> Authorization session mismatch. This can happen if you followed a link from
> another person or your session expired. Please try authenticating again.

If you hit this repeatedly on a trusted single-user deployment, `never` removes
the binding-cookie check and the symptom.

#### Risks of `never`

Setting `never` (`require_authorization_consent=False`) disables **both** the
consent screen **and** the consent binding-cookie verification. Concretely:

- ⚠️ **No confused-deputy protection.** Any party who can drive the MCP client
  through the authorization flow can complete it silently, without an approval
  step. Only acceptable when there is a **single, trusted user** and the client
  itself is trusted (typical for a personal/single-tenant deployment).
- It does **not** weaken token validation, scope checks, PKCE, or issuer/audience
  validation — those remain in force regardless of consent mode.
- Recommended **only** for single-tenant deployments. For any multi-user or
  shared setup, prefer `remember` (or `always`) and accept the occasional
  re-authentication prompt.

> **Note:** the recurring "login page reopens every few minutes" problem is a
> **separate** issue caused by a missing refresh token, not by the consent mode.
> Ensure the `offline_access` scope is requested so the IdP issues a refresh
> token and the client can refresh silently instead of re-authorizing.

### Access Token TTL (`FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS`)

By default fastmcp's OAuth proxy mirrors the upstream IdP `expires_in` on the
access token it issues to MCP clients, so a short IdP lifetime (often 1 hour or
less) becomes the client-facing lifetime too. Clients that keep tokens only in
process memory (e.g. `mcp-remote`) then renew frequently via refresh grant, and
any hiccup in that path surfaces as a re-authentication prompt.

`FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS` decouples the client-facing token
lifetime from the upstream one. It defaults to **86400 (24 hours)** when unset.

```shell
# .env file — optional, defaults to 86400 (24h) when unset
DEV_FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS=86400
```

| Value          | Behaviour                                                       |
| -------------- | --------------------------------------------------------------- |
| unset          | Client-facing token lives 24 hours                              |
| `N > 0`        | Client-facing token lives `N` seconds                           |
| `0` (or `< 0`) | Opt out: mirror the upstream IdP `expires_in` (fastmcp default) |

This is **not** a security relaxation: the FastMCP token is a _reference_
token. On every request the proxy re-validates the underlying upstream token
against the IdP and transparently refreshes it when expired. A revoked or
expired upstream session therefore fails immediately, regardless of how much
lifetime is left on the client-facing token. When the IdP issues no refresh
token, fastmcp caps the client-facing lifetime at the upstream `expires_in`
anyway.

> Requires fastmcp >= 3.4 (`fastmcp_access_token_expiry_seconds` on the OAuth
> proxy).

## Security & Authentication Flows

The MCP server supports multiple security configurations depending on your deployment needs.

### Supported OAuth 2.0 Flows

| Flow                                  | Use Case                                         | Configuration                        |
| ------------------------------------- | ------------------------------------------------ | ------------------------------------ |
| **Authorization Code + PKCE**         | Interactive clients (Claude Desktop, mcp-remote) | `JWKS_ENABLED=true` with OIDC config |
| **Client Credentials**                | Machine-to-machine, service accounts             | `JWKS_ENABLED=true` with OIDC config |
| **Dynamic Client Registration (DCR)** | Auto-registration for MCP clients                | Enabled automatically with OIDC      |

### OAuth Proxy Architecture

When OAuth is enabled, the MCP server acts as an **OAuth Proxy**. This architecture allows the MCP server to handle OAuth flows on behalf of MCP clients, simplifying authentication for AI assistants.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   MCP Client    │────▶│   MCP Server    │────▶│   Identity      │
│  (mcp-remote)   │     │  (OAuth Proxy)  │     │   Provider      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        │  1. Discovery         │                       │
        │──────────────────────▶│                       │
        │  /.well-known/...     │                       │
        │                       │                       │
        │  2. DCR (register)    │                       │
        │──────────────────────▶│                       │
        │                       │                       │
        │  3. Authorization     │  4. Redirect to IdP   │
        │──────────────────────▶│──────────────────────▶│
        │                       │                       │
        │                       │  5. Auth Code         │
        │                       │◀──────────────────────│
        │  6. Token Exchange    │                       │
        │◀──────────────────────│                       │
        │                       │                       │
        │  7. MCP Requests      │  8. In-process ASGI   │
        │  (with Bearer token)  │     call to pygeoapi  │
        │──────────────────────▶│──────────────────────▶│
```

**OAuth Flow Steps:**

1. **Discovery**: The MCP client fetches OAuth metadata from `/.well-known/oauth-protected-resource/mcp/`
2. **Dynamic Client Registration**: The client registers itself with the MCP server's OAuth proxy
3. **Authorization Request**: The client initiates the OAuth flow
4. **IdP Redirect**: The OAuth proxy redirects to the upstream Identity Provider
5. **Auth Code Return**: The IdP returns an authorization code
6. **Token Exchange**: The OAuth proxy exchanges the code for tokens and issues its own JWT
7. **MCP Requests**: The client makes authenticated MCP requests with the Bearer token
8. **Internal API Calls**: The MCP server reaches pygeoapi in-process through `httpx.ASGITransport` against a raw sub-app — no network hop and no shared secret; the OAuth middleware chain is simply not mounted on this internal path

### RFC Compliance

The MCP server implements several OAuth-related RFCs:

| RFC          | Title                                   | Description                                       |
| ------------ | --------------------------------------- | ------------------------------------------------- |
| **RFC 8414** | OAuth 2.0 Authorization Server Metadata | Enables automatic discovery of OAuth endpoints    |
| **RFC 9728** | OAuth 2.0 Protected Resource Metadata   | Describes protected resources and required scopes |
| **RFC 7636** | Proof Key for Code Exchange (PKCE)      | Prevents authorization code interception attacks  |
| **RFC 7591** | OAuth 2.0 Dynamic Client Registration   | Allows clients to register automatically          |
| **RFC 6750** | Bearer Token Usage                      | Proper error handling for authentication failures |

### Security Features

| Feature                       | Description                                                                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **JWT Validation**            | Tokens are validated using JWKS from the IdP                                                                                   |
| **Opaque Token Support**      | Supports IdPs that return opaque tokens (e.g., Logto without API Resources)                                                    |
| **RFC 6750 Compliance**       | Proper error handling distinguishing "no token" vs "invalid token"                                                             |
| **In-Process Internal Calls** | MCP-to-pygeoapi calls run in-process via `httpx.ASGITransport` on a non-routable virtual host — no bypass key or header exists |
| **Scope Validation**          | Configurable required scopes for access control                                                                                |
| **PKCE Support**              | Prevents authorization code interception in public clients                                                                     |

### Supported Identity Providers

The MCP server is provider-agnostic and works with any OIDC-compliant Identity Provider:

| Provider     | Status    | Notes                                      |
| ------------ | --------- | ------------------------------------------ |
| **Logto**    | Tested    | OAuth proxy with DCR, opaque token support |
| **Auth0**    | Supported | Full OIDC support                          |
| **Keycloak** | Supported | Full OIDC and OPA integration              |
| **Okta**     | Supported | Standard OIDC flows                        |
| **Azure AD** | Supported | Microsoft identity platform                |
| **Google**   | Supported | Google OAuth 2.0                           |

## Using the MCP Server

### Connect Claude Desktop (native connector)

[Claude Desktop](https://claude.ai/desktop) supports remote MCP servers natively as **custom connectors** — no local shim or config-file edit required. This is the recommended path:

1. Open **Settings → Connectors → Add custom connector**
2. Paste the server URL: `https://your-domain.com/mcp/` (the trailing slash is optional — both variants are served)
3. On first use, complete the OAuth login in the browser popup; the connector then refreshes tokens silently

!!! warning "Avoid running mcp-remote alongside the connector"
If an older `mcp-remote`-based entry for the same server is still present in `claude_desktop_config.json`, remove it: the two clients race through the OAuth flow and the mcp-remote process can wedge on its fixed callback port (43711), leaving the tools list stuck.

### Connect stdio-only clients (mcp-remote)

For MCP clients that only speak stdio, front the server with [mcp-remote](https://www.npmjs.com/package/mcp-remote) in the client configuration file (for Claude Desktop: `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS, `%APPDATA%\Claude\claude_desktop_config.json` on Windows):

```json
{
  "mcpServers": {
    "fastgeoapi": {
      "command": "npx",
      "args": ["mcp-remote", "https://your-domain.com/mcp/"]
    }
  }
}
```

For local development over plain HTTP, add the `--allow-http` flag:

```json
{
  "mcpServers": {
    "fastgeoapi": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:5000/mcp/", "--allow-http"]
    }
  }
}
```

!!! note "mcp-remote caveats"
mcp-remote keeps tokens only in process memory (every restart re-runs the full OAuth dance) and binds a fixed OAuth callback port. If the client loops on authentication, check for zombie processes with `lsof -i :43711` and kill them.

### Connect via Streamable HTTP

fastmcp 3.x serves MCP over the Streamable HTTP transport (the legacy `/mcp/sse` endpoint no longer exists). Clients with native remote MCP support connect directly to:

```
http://localhost:5000/mcp/
```

Or with HTTPS in production:

```
https://your-domain.com/mcp/
```

### Test the MCP Server

You can test the MCP server endpoints directly:

```shell
# Check the MCP endpoint is alive (Streamable HTTP): expect 401 with OAuth
# enabled, 406 without the proper Accept headers — both mean it is up
curl -i http://localhost:5000/mcp/

# Get OAuth metadata (when OAuth is enabled)
curl http://localhost:5000/.well-known/oauth-protected-resource/mcp/

# Get authorization server metadata (RFC 8414 path-aware)
curl http://localhost:5000/.well-known/oauth-authorization-server/mcp
```

## Available MCP Tools

The MCP server automatically generates tools from the pygeoapi OpenAPI specification. The available tools depend on your pygeoapi configuration and enabled OGC API standards.

### Core OGC API Tools

Tool names come from the OpenAPI `operationId`s, so collection-specific tools embed the collection name (the demo configuration with the `lakes` and `obs` collections yields 27 tools). For example:

| Tool                        | Description                                          | OGC API  |
| --------------------------- | ---------------------------------------------------- | -------- |
| `getLandingPage`            | Get the API landing page with links to all resources | Common   |
| `getConformanceDeclaration` | Get OGC API conformance classes                      | Common   |
| `getCollections`            | List all available feature collections               | Features |
| `describeLakesCollection`   | Get metadata for the `lakes` collection              | Features |
| `getLakesFeatures`          | Query features from `lakes` with filters             | Features |
| `getLakesFeature`           | Get a specific `lakes` feature by ID                 | Features |
| `getLakesQueryables`        | Get queryable properties of the `lakes` collection   | Features |
| `getLakesSchema`            | Get the JSON Schema of the `lakes` collection        | Features |

### OGC API - Processes Tools

If OGC API - Processes is enabled in your pygeoapi configuration (names below are for the demo `hello-world` process; note that fastmcp sanitizes `-` to `_`):

| Tool                         | Description                               |
| ---------------------------- | ----------------------------------------- |
| `getProcesses`               | List all available processes              |
| `describeHello_worldProcess` | Get details about the process             |
| `executeHello_worldJob`      | Execute the process with input parameters |
| `getJobs` / `getJob`         | List jobs / get the status of a job       |
| `getJobResults`              | Get the results of a completed job        |

### Example Tool Usage

When using Claude Desktop with the MCP server, you can ask questions like:

- "What feature collections are available?"
- "Show me the first 10 features from the 'lakes' collection"
- "What are the queryable properties for the 'buildings' collection?"
- "Get the feature with ID 'building-123' from the buildings collection"

Claude will automatically use the appropriate MCP tools to fulfill these requests.

## OAuth Discovery Endpoints

When OAuth is enabled, the following RFC-compliant endpoints are available:

| Endpoint                                      | RFC       | Description                                |
| --------------------------------------------- | --------- | ------------------------------------------ |
| `/.well-known/oauth-protected-resource/mcp/`  | RFC 9728  | Protected resource metadata                |
| `/.well-known/oauth-authorization-server/mcp` | RFC 8414  | Authorization server metadata (path-aware) |
| `/.well-known/openid-configuration`           | OIDC 1.0  | OIDC discovery alias (fastmcp >= 3.4)      |
| `/mcp/register`                               | RFC 7591  | Dynamic client registration                |
| `/mcp/authorize`                              | OAuth 2.0 | Authorization endpoint                     |
| `/mcp/token`                                  | OAuth 2.0 | Token endpoint                             |

## Architecture

The following diagram shows how the MCP server integrates with the fastgeoapi architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                      Claude Desktop                              │
│                      or MCP Client                               │
└─────────────────────────────┬───────────────────────────────────┘
                              │ MCP Protocol (Streamable HTTP)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        fastgeoapi                                │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                   MCP Server (/mcp)                         │ │
│  │                                                             │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │ │
│  │  │ OAuth Proxy  │  │ Tool Router  │  │ HTTP Transport   │  │ │
│  │  │              │  │              │  │                  │  │ │
│  │  │ - DCR        │  │ - OpenAPI    │  │ - Single /mcp/   │  │ │
│  │  │ - PKCE       │  │   parsing    │  │   endpoint       │  │ │
│  │  │ - Token mgmt │  │ - Tool gen   │  │ - Event streaming│  │ │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              │ In-process internal calls         │
│                              │ (httpx.ASGITransport, no key)     │
│                              ▼                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              pygeoapi OGC API (/geoapi)                     │ │
│  │                                                             │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │ │
│  │  │  Features    │  │  Processes   │  │  Collections     │  │ │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Component Responsibilities:**

| Component          | Responsibility                                                                                |
| ------------------ | --------------------------------------------------------------------------------------------- |
| **OAuth Proxy**    | Handles OAuth flows, DCR, PKCE, and token management                                          |
| **Tool Router**    | Parses OpenAPI spec and routes tool calls to API endpoints                                    |
| **HTTP Transport** | Stateless Streamable HTTP communication (fresh transport per request)                         |
| **ASGI Transport** | Routes MCP-to-pygeoapi calls in-process to a raw sub-app (no auth chain on the internal path) |

### Stateless Transport

The MCP endpoint runs the Streamable HTTP transport in **stateless mode** (`stateless_http=True`): every request is self-contained and no session state lives on the server between requests.

This is a deliberate choice for ephemeral deployments. With the default _stateful_ transport, the server keeps per-session state bound to the `mcp-session-id` negotiated at `initialize`; anything that recycles the process — an auto-suspending machine (Fly.io `auto_stop_machines`), a redeploy, a serverless cold start — strands connected clients on a dead session. The observable symptom in Claude Desktop: the connector still shows "connected", but tool calls fail (e.g. "couldn't send tool approval") until the client is reconnected by hand.

In stateless mode those events are transparent: the next request simply works, whether or not the process was suspended, resumed, or rebuilt in between.

The trade-off is that the server cannot push server-initiated messages (progress notifications, sampling, subscriptions). For this server — a tools-only surface generated from the pygeoapi OpenAPI document — nothing is lost.

## Troubleshooting

### MCP Server Not Starting

If the MCP server doesn't start, check:

1. `FASTGEOAPI_WITH_MCP=true` is set in your `.env` file
2. The `pygeoapi-openapi.yml` file exists and is valid
3. Check the logs for any OpenAPI parsing errors

```shell
# Check if OpenAPI file exists
ls -la pygeoapi-openapi.yml

# Start with debug logging
DEV_LOG_LEVEL=debug fastgeoapi run
```

### OAuth Authentication Failing

If OAuth authentication fails:

1. Verify your OIDC well-known endpoint is accessible:

   ```shell
   curl https://your-idp.example.com/.well-known/openid-configuration
   ```

2. Check that client ID and secret are correct

3. Ensure the redirect URI is configured in your IdP:
   - For local development: `http://localhost:5000/mcp/auth/callback`
   - For production: `https://your-domain.com/mcp/auth/callback`

### mcp-remote Connection Issues

If mcp-remote can't connect:

1. Ensure the MCP server is running and accessible
2. Check that the URL ends with a trailing slash: `http://localhost:5000/mcp/`
3. For HTTP (non-HTTPS), use the `--allow-http` flag
4. Check for CORS issues in browser-based clients

### Client Shows "Connected" but Tool Calls Fail

If the client UI reports the server as connected but tool invocations error out (Claude Desktop: "couldn't send tool approval"), the client is usually holding a stale connection or session from before a server suspend/redeploy:

1. Start a **new conversation** (MCP sessions are per-conversation in Claude Desktop)
2. If that's not enough, disable and re-enable the connector (or restart the client)

Server-side this class of problem is mitigated by the [stateless transport](#stateless-transport): requests never depend on prior server state, so once the client opens a fresh connection everything works without re-authentication.

### Enable Debug Logging

Enable debug logging to see detailed MCP server activity:

```shell
# In .env file
DEV_LOG_LEVEL=debug
```

This will show:

- OAuth flow steps
- Tool invocations
- API calls to pygeoapi
- Token validation results

## References

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [mcpauth Library](https://github.com/alonsosilvaallende/mcpauth)
- [OAuth 2.0 RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)
- [OAuth 2.0 Protected Resource Metadata RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728)
- [OGC API Standards](https://ogcapi.ogc.org/)
