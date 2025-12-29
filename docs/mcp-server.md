# MCP Server (Model Context Protocol)

fastgeoapi includes an optional integrated MCP server that exposes OGC API endpoints as tools for AI assistants and LLM-based applications. The MCP server is built using [FastMCP](https://github.com/jlowin/fastmcp) and automatically generates tools from the pygeoapi OpenAPI specification.

## What is MCP?

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) is an open standard that enables AI assistants to interact with external tools and data sources. By implementing an MCP server, fastgeoapi allows AI assistants like Claude Desktop to:

- Query geospatial feature collections
- Retrieve metadata about available datasets
- Execute OGC API processes
- Access conformance information

## Features

| Feature                         | Description                                                                         |
| ------------------------------- | ----------------------------------------------------------------------------------- |
| **Automatic Tool Generation**   | Tools are generated from the OGC API OpenAPI spec                                   |
| **OAuth Authentication**        | Supports OIDC authentication with any OAuth provider                                |
| **RFC 9728 Compliant**          | Implements OAuth 2.0 Protected Resource Metadata                                    |
| **Dynamic Client Registration** | Compatible with mcp-remote and other MCP clients                                    |
| **Provider Agnostic**           | Uses [mcpauth](https://github.com/alonsosilvaallende/mcpauth) for multi-IdP support |
| **SSE Transport**               | Server-Sent Events for real-time communication                                      |

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
        │  7. MCP Requests      │  8. Internal API call │
        │  (with Bearer token)  │  (bypasses auth)      │
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
8. **Internal API Calls**: The MCP server calls pygeoapi with an internal bypass key

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

| Feature                  | Description                                                                 |
| ------------------------ | --------------------------------------------------------------------------- |
| **JWT Validation**       | Tokens are validated using JWKS from the IdP                                |
| **Opaque Token Support** | Supports IdPs that return opaque tokens (e.g., Logto without API Resources) |
| **RFC 6750 Compliance**  | Proper error handling distinguishing "no token" vs "invalid token"          |
| **Internal API Bypass**  | MCP-to-pygeoapi calls use an internal key to bypass authentication          |
| **Scope Validation**     | Configurable required scopes for access control                             |
| **PKCE Support**         | Prevents authorization code interception in public clients                  |

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

### Connect Claude Desktop

[Claude Desktop](https://claude.ai/desktop) supports MCP servers natively. Add the following to your configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

#### Without Authentication

```json
{
  "mcpServers": {
    "fastgeoapi": {
      "command": "npx",
      "args": ["mcp-remote", "http://localhost:5000/mcp/"]
    }
  }
}
```

#### With OAuth Authentication

When OAuth is enabled, mcp-remote handles authentication automatically:

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

!!! note "HTTP Flag"
The `--allow-http` flag is required for local development. In production with HTTPS, remove this flag.

#### Production Configuration

For production deployments with HTTPS:

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

### Connect via Direct SSE

For clients that support Server-Sent Events directly, connect to:

```
http://localhost:5000/mcp/sse
```

Or with HTTPS in production:

```
https://your-domain.com/mcp/sse
```

### Test the MCP Server

You can test the MCP server endpoints directly:

```shell
# Check if MCP server is running (SSE endpoint)
curl -N http://localhost:5000/mcp/sse

# Get OAuth metadata (when OAuth is enabled)
curl http://localhost:5000/.well-known/oauth-protected-resource/mcp/

# Get authorization server metadata
curl http://localhost:5000/mcp/.well-known/oauth-authorization-server
```

## Available MCP Tools

The MCP server automatically generates tools from the pygeoapi OpenAPI specification. The available tools depend on your pygeoapi configuration and enabled OGC API standards.

### Core OGC API Tools

| Tool             | Description                                          | OGC API  |
| ---------------- | ---------------------------------------------------- | -------- |
| `getLandingPage` | Get the API landing page with links to all resources | Common   |
| `getConformance` | Get OGC API conformance classes                      | Common   |
| `getCollections` | List all available feature collections               | Features |
| `getCollection`  | Get metadata for a specific collection               | Features |
| `getItems`       | Query features from a collection with filters        | Features |
| `getItem`        | Get a specific feature by ID                         | Features |
| `getQueryables`  | Get queryable properties for a collection            | Features |

### OGC API - Processes Tools

If OGC API - Processes is enabled in your pygeoapi configuration:

| Tool             | Description                             |
| ---------------- | --------------------------------------- |
| `getProcesses`   | List all available processes            |
| `getProcess`     | Get details about a specific process    |
| `executeProcess` | Execute a process with input parameters |
| `getJob`         | Get the status of a job                 |
| `getJobResults`  | Get the results of a completed job      |

### Example Tool Usage

When using Claude Desktop with the MCP server, you can ask questions like:

- "What feature collections are available?"
- "Show me the first 10 features from the 'lakes' collection"
- "What are the queryable properties for the 'buildings' collection?"
- "Get the feature with ID 'building-123' from the buildings collection"

Claude will automatically use the appropriate MCP tools to fulfill these requests.

## OAuth Discovery Endpoints

When OAuth is enabled, the following RFC-compliant endpoints are available:

| Endpoint                                      | RFC       | Description                   |
| --------------------------------------------- | --------- | ----------------------------- |
| `/.well-known/oauth-protected-resource/mcp/`  | RFC 9728  | Protected resource metadata   |
| `/mcp/.well-known/oauth-authorization-server` | RFC 8414  | Authorization server metadata |
| `/mcp/register`                               | RFC 7591  | Dynamic client registration   |
| `/mcp/authorize`                              | OAuth 2.0 | Authorization endpoint        |
| `/mcp/token`                                  | OAuth 2.0 | Token endpoint                |

## Architecture

The following diagram shows how the MCP server integrates with the fastgeoapi architecture:

```
┌─────────────────────────────────────────────────────────────────┐
│                      Claude Desktop                              │
│                      or MCP Client                               │
└─────────────────────────────┬───────────────────────────────────┘
                              │ MCP Protocol (SSE/HTTP)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        fastgeoapi                                │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │                   MCP Server (/mcp)                         │ │
│  │                                                             │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │ │
│  │  │ OAuth Proxy  │  │ Tool Router  │  │ SSE Transport    │  │ │
│  │  │              │  │              │  │                  │  │ │
│  │  │ - DCR        │  │ - OpenAPI    │  │ - Bidirectional  │  │ │
│  │  │ - PKCE       │  │   parsing    │  │   communication  │  │ │
│  │  │ - Token mgmt │  │ - Tool gen   │  │ - Event stream   │  │ │
│  │  └──────────────┘  └──────────────┘  └──────────────────┘  │ │
│  └────────────────────────────────────────────────────────────┘ │
│                              │                                   │
│                              │ Internal API calls                │
│                              │ (X-MCP-Internal-Key header)       │
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

| Component         | Responsibility                                             |
| ----------------- | ---------------------------------------------------------- |
| **OAuth Proxy**   | Handles OAuth flows, DCR, PKCE, and token management       |
| **Tool Router**   | Parses OpenAPI spec and routes tool calls to API endpoints |
| **SSE Transport** | Manages bidirectional communication with MCP clients       |
| **Internal Key**  | Bypasses authentication for MCP-to-pygeoapi calls          |

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
   - For local development: `http://localhost:5000/mcp/callback`
   - For production: `https://your-domain.com/mcp/callback`

### mcp-remote Connection Issues

If mcp-remote can't connect:

1. Ensure the MCP server is running and accessible
2. Check that the URL ends with a trailing slash: `http://localhost:5000/mcp/`
3. For HTTP (non-HTTPS), use the `--allow-http` flag
4. Check for CORS issues in browser-based clients

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
