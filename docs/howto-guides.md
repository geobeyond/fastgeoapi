# How-to Guides

This section contains practical guides for configuring and using fastgeoapi features.

## Configure Identity and Access Management

TBD

### Run Keycloak and Open Policy Agent

TBD

## Health and Readiness Probes

fastgeoapi exposes two probe endpoints at the application root — outside the `FASTGEOAPI_CONTEXT` path and outside every authentication chain, so orchestrators (Fly.io checks, Kubernetes probes, control planes) can call them without credentials in any auth mode:

- `GET /healthz` — liveness: returns `200 {"status": "ok"}` as soon as the process is serving
- `GET /readyz` — readiness: returns `200 {"status": "ready"}` once the pygeoapi OpenAPI document is available, `503` otherwise

Related knob: `FASTGEOAPI_CACHE_DIR` relocates the external-refs schema cache (default `<cwd>/.cache`) for containerized layouts with read-only or non-stable working directories.

## Configure the MCP Server

fastgeoapi includes an optional integrated MCP server that exposes OGC API endpoints as tools for AI assistants and LLM-based applications.

The MCP server provides:

- **Automatic Tool Generation** from the OGC API OpenAPI specification
- **OAuth Authentication** with any OIDC-compliant provider
- **Dynamic Client Registration** for seamless integration with MCP clients
- **Streamable HTTP Transport** for real-time communication (fastmcp 3.x)

For complete configuration instructions, security flows, and usage examples, see the dedicated [MCP Server guide](mcp-server.md).
