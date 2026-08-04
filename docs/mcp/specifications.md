# Supported specifications

The fastgeoapi MCP server plays **two roles** in an identity-secured
MCP deployment: it is an **MCP Server** (the protected resource AI
agents talk to) and it embeds its own **OAuth Authorization Server**
(the OIDC proxy that faces MCP clients, independent of the upstream
Identity Provider). The matrix below describes what each role
supports, following the structure used by the OpenID AIIM
interoperability program.

## Support matrix

Legend: ✅ supported and verifiable on a live deployment · 🧪 supported
upstream, end-to-end verification in progress · 🗺️ on the roadmap ·
❌ not supported (by design where noted).

### As MCP Server (protected resource)

| Specification | Status | Notes |
| --- | --- | --- |
| MCP Streamable HTTP transport (stateless) | ✅ | Every request is self-contained: restarts, redeploys and autosuspend are transparent to clients |
| OAuth 2.0 Protected Resource Metadata (RFC 9728) | ✅ | `/.well-known/oauth-protected-resource/mcp/`, advertised in the `WWW-Authenticate` challenge |
| Bearer token usage and error semantics (RFC 6750) | ✅ | Distinguishes missing vs invalid token in challenges |
| `scope` parameter in `WWW-Authenticate` | 🧪 | Under verification |
| OAuth token based access with own Resource AS | ✅ | The embedded OAuth proxy issues the tokens this server accepts |

### As OAuth Authorization Server (embedded OIDC proxy)

| Specification | Status | Notes |
| --- | --- | --- |
| OAuth 2.1-style authorization code + PKCE (RFC 7636) | ✅ | S256; the proxy fronts any OIDC-compliant upstream IdP |
| Authorization Server Metadata (RFC 8414) | ✅ | Path-aware, with the `openid-configuration` alias and no-trailing-slash variants |
| Dynamic Client Registration (RFC 7591) | ✅ | With redirect-URI validation (unsafe schemes and unregistered URIs rejected) |
| Refresh token rotation | ✅ | One-time-use refresh tokens; `offline_access` supported |
| Client-facing token TTL decoupled from IdP `expires_in` | ✅ | `FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS` |
| **CIMD** — Client ID Metadata Document ([draft-ietf-oauth-client-id-metadata-document](https://datatracker.ietf.org/doc/draft-ietf-oauth-client-id-metadata-document/)) | 🧪 | Enabled and advertised (`client_id_metadata_document_supported: true`); see the CIMD detail below |
| Mixed-key JWKS validation (RSA / EC / Ed25519) | ✅ | Unsupported key types in an IdP's JWKS are skipped instead of failing the whole set — pairs with Keycloak, Ory Hydra, Rauthy out of the box |
| **EMA** — Enterprise Managed Authorization ([ID-JAG](https://datatracker.ietf.org/doc/draft-ietf-oauth-identity-assertion-authz-grant/)) | 🗺️ | Accepting the Identity Assertion JWT Authorization Grant at the embedded AS is on the roadmap (tracking FastMCP 4 / SEP-990) |
| MTLS client authentication (RFC 8705) | ❌ | Not supported |

### CIMD feature detail

| CIMD feature | Status | Notes |
| --- | --- | --- |
| Client ID as URL, metadata document fetch | 🧪 | SSRF-hardened fetcher (loopback and private ranges rejected, including IPv6 transition addresses) |
| `redirect_uris` from the metadata document | 🧪 | Redirects validated against the document |
| `jwks_uri` / `jwks` from the metadata document | 🧪 | End-to-end verification in progress |
| Shared-secret client authentication for CIMD clients | ❌ by design | URL-identified clients cannot hold a usable shared secret; key-based methods only |

## Supported OAuth flows

| Flow                                  | Use Case                                         | Configuration                        |
| ------------------------------------- | ------------------------------------------------ | ------------------------------------ |
| **Authorization Code + PKCE**         | Interactive clients (Claude Desktop, mcp-remote) | `JWKS_ENABLED=true` with OIDC config |
| **Client Credentials**                | Machine-to-machine, service accounts             | `JWKS_ENABLED=true` with OIDC config |
| **Dynamic Client Registration (DCR)** | Auto-registration for MCP clients                | Enabled automatically with OIDC      |

## OAuth Proxy Architecture

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

## Security Features

| Feature                       | Description                                                                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **Fail-closed startup guard** | With MCP enabled and no authentication configured, the server refuses to start unless passthrough mode is explicitly opted in |
| **JWT Validation**            | Tokens are validated using JWKS from the IdP                                                                                   |
| **Opaque Token Support**      | Supports IdPs that return opaque tokens (e.g., Logto without API Resources)                                                    |
| **RFC 6750 Compliance**       | Proper error handling distinguishing "no token" vs "invalid token"                                                             |
| **In-Process Internal Calls** | MCP-to-pygeoapi calls run in-process via `httpx.ASGITransport` on a non-routable virtual host — no bypass key or header exists |
| **Scope Validation**          | Configurable required scopes for access control                                                                                |
| **PKCE Support**              | Prevents authorization code interception in public clients                                                                     |

## Supported Identity Providers

The MCP server is provider-agnostic and works with any OIDC-compliant Identity Provider:

| Provider     | Status    | Notes                                      |
| ------------ | --------- | ------------------------------------------ |
| **Logto**    | Tested    | OAuth proxy with DCR, opaque token support |
| **Auth0**    | Supported | Full OIDC support                          |
| **Keycloak** | Supported | Full OIDC and OPA integration              |
| **Okta**     | Supported | Standard OIDC flows                        |
| **Azure AD** | Supported | Microsoft identity platform                |
| **Google**   | Supported | Google OAuth 2.0                           |
