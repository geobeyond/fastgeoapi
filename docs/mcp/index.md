# MCP Server

fastgeoapi ships a production Model Context Protocol (MCP) server that
exposes the protected OGC APIs as tools for AI agents, with a built-in
OAuth authorization layer.

This section covers:

- **[Configuration](configuration.md)** — how to enable the MCP server
  and tune its authentication
- **[Supported specifications](specifications.md)** — the standards
  matrix (OAuth 2.1, CIMD, EMA and related RFCs)
- **[Getting started](getting-started.md)** — connect a client and
  call your first tool

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
| **Provider Agnostic**           | Works with any OIDC-compliant IdP via fastmcp's OIDCProxy                              |
| **Stateless Streamable HTTP**   | Single-endpoint transport; every request is self-contained (suspend/redeploy friendly) |

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
