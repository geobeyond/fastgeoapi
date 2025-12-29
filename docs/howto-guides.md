# How-to Guides

This section contains practical guides for configuring and using fastgeoapi features.

## Configure Identity and Access Management

TBD

### Run Keycloak and Open Policy Agent

TBD

## Configure the MCP Server

fastgeoapi includes an optional integrated MCP server that exposes OGC API endpoints as tools for AI assistants and LLM-based applications.

The MCP server provides:

- **Automatic Tool Generation** from the OGC API OpenAPI specification
- **OAuth Authentication** with any OIDC-compliant provider
- **Dynamic Client Registration** for seamless integration with MCP clients
- **SSE Transport** for real-time communication

For complete configuration instructions, security flows, and usage examples, see the dedicated [MCP Server guide](mcp-server.md).
