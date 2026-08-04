# Configuration

How to enable the MCP server and configure its authentication.

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
# Explicit opt-in: without authentication configured, MCP refuses to
# start unless you acknowledge the unauthenticated (passthrough) mode.
DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED=true

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

### Fail-Closed Authentication Guard (`FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED`)

When `FASTGEOAPI_WITH_MCP=true` and no MCP authentication is configured (`JWKS_ENABLED` and `OIDC_WELL_KNOWN_ENDPOINT`), the server **refuses to start** instead of silently exposing every generated MCP tool without authentication. This is fail-closed by design: the MCP-to-pygeoapi hop runs in-process against a raw sub-app with no auth middleware, so an unauthenticated MCP endpoint would leak the entire API even when the regular HTTP surface is protected — and a single typo'd OIDC environment variable in production would otherwise do exactly that, silently.

The only way to run MCP without authentication is the explicit first-class **passthrough mode**:

```shell
# .env file — explicit opt-in, defaults to false
DEV_FASTGEOAPI_MCP_ALLOW_UNAUTHENTICATED=true
```

On boot in passthrough mode the server logs a loud warning stating that every MCP tool and the pygeoapi API behind them are publicly accessible. Use it for local development and for intentionally-anonymous deployments; never as a workaround for a misconfigured IdP.

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

