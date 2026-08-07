# Getting started

Connect an MCP client and call your first tool.

### Connect Claude Desktop (native connector)

[Claude Desktop](https://claude.ai/desktop) supports remote MCP servers natively as **custom connectors** — no local shim or config-file edit required. This is the recommended path:

1. Open **Settings → Connectors → Add custom connector**
2. Paste the server URL: `https://your-domain.com/mcp/` (the trailing slash is optional — both variants are served)
3. On first use, complete the OAuth login in the browser popup; the connector then refreshes tokens silently

!!! warning "Avoid running mcp-remote alongside the connector"
If an older `mcp-remote`-based entry for the same server is still present in `claude_desktop_config.json`, remove it: the two clients race through the OAuth flow and the mcp-remote process can wedge on its fixed callback port (43711), leaving the tools list stuck.

!!! info "Claude identifies itself with CIMD, not Dynamic Client Registration"
Claude presents a URL as its `client_id` (`https://claude.ai/oauth/mcp-oauth-client-metadata`) and publishes its own metadata there, rather than registering through DCR. Two practical consequences: the authorization server must have CIMD enabled (it is, by default), and the connector never holds a client secret — the flow is protected by PKCE.

    Worth knowing when debugging: a failure on the CIMD path is invisible to a DCR-based test. If the connector cannot authorize while a manually registered client can, replay Claude's exact request — the `client_id` URL is in the server access log — instead of assuming the two paths behave alike.

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

### Client Shows "Connected" but the Tool List Is Empty

Different symptom, different cause: the connector is green and there is nothing to call — the tools simply aren't listed.

"Connected" reflects the OAuth grant the client has stored, not a live capability check. If that access token is no longer accepted — it outlived its TTL and the refresh failed, or it was minted by a previous server build — the client's `tools/list` is answered `401` and it keeps an **empty** tool registry rather than re-running authorization. Nothing recovers on its own.

Server-side the signature is unmistakable: repeated

```
POST /mcp HTTP/1.1" 401 Unauthorized
```

from the client's address, with **no** `POST /mcp/token` in between — the client is retrying with the dead token instead of refreshing it.

The fix is to disable and re-enable the connector, which re-runs the authorization dance. If it comes back on a regular cadence, raise `FASTGEOAPI_MCP_ACCESS_TOKEN_EXPIRY_SECONDS` (see [Configuration](configuration.md)): a longer client-facing TTL is safe here because the token is a reference token — the upstream session is re-validated on every request regardless.

### Client Shows "Connected" but Tool Calls Fail

If the client UI reports the server as connected but tool invocations error out (Claude Desktop: "couldn't send tool approval"), the client is usually holding a stale connection or session from before a server suspend/redeploy:

1. Start a **new conversation** (MCP sessions are per-conversation in Claude Desktop)
2. If that's not enough, disable and re-enable the connector (or restart the client)

Server-side this class of problem is mitigated by the [stateless transport](index.md#stateless-transport): requests never depend on prior server state, so once the client opens a fresh connection everything works without re-authentication.

### Exploring with third-party clients

Two failure modes look identical from a generic MCP CLI — an opaque
"server returned an error" — but have different causes.

**The server requires authentication.** With OAuth enabled every MCP
request without a token is answered `401` plus the RFC 6750 challenge.
Tools that cannot authenticate simply cannot list tools. Use a client
that performs the OAuth flow:

```bash
npx @modelcontextprotocol/inspector
# then point it at https://your-host/mcp/ and complete the browser flow
```

**The client speaks a newer protocol.** Recent tooling defaults to the
sessionless protocol `2026-07-28`, which this build does not negotiate
yet (see [Protocol versions](specifications.md#protocol-versions)).
Clients that expose a legacy mode work in full:

```bash
# against a server running without authentication
uvx mcp-explorer list --legacy http://127.0.0.1:5000/mcp/
uvx mcp-explorer info --legacy http://127.0.0.1:5000/mcp/
```

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
- [OAuth 2.0 RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749)
- [OAuth 2.0 Protected Resource Metadata RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728)
- [OGC API Standards](https://ogcapi.ogc.org/)
