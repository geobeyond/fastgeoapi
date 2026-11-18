---
icon: material/robot-outline
---

# :material-robot-outline: MCP Server

fastgeoapi ships a production Model Context Protocol (MCP) server that
exposes the protected OGC APIs as tools for AI agents, with a built-in
OAuth authorization layer.

This section covers:

- **[Configuration](../../operators/how-to/enabling-mcp.md)** — how to enable the MCP server
  and tune its authentication
- **[Supported specifications](../reference/mcp-specifications.md)** — the standards
  matrix (OAuth 2.1, CIMD, EMA and related RFCs)
- **[Getting started](../tutorials/connecting-an-mcp-client.md)** — connect a client and
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

## Skills

Besides the tools, the server offers [agent
skills](https://agentskills.io/) that explain how the OGC API operations
fit together: which one to call first, which parameters narrow the
answer, and what to check when the answer is empty or wrong. They
describe each operation by its HTTP path, so they hold for any OGC API
server; the server instructions tell the client which tool calls which
path.

| Skill                     | What it teaches                                                                            | Served when the API has |
| ------------------------- | ------------------------------------------------------------------------------------------ | ----------------------- |
| `ogcapi-orientation`      | the landing page, conformance, collections and their links                                 | always                  |
| `ogcapi-features`         | items, `bbox`, `datetime`, paging with the `next` link, `properties`, `sortby`, queryables | items on a collection   |
| `ogcapi-features/cql2.md` | CQL2 filters in text and JSON                                                              | `filter` on the items   |
| `ogcapi-processes`        | process descriptions, `inputs`, synchronous and asynchronous runs, jobs                    | a process to execute    |
| `ogcapi-maps`             | map images, `bbox`, `width`, `height`                                                      | a map on a collection   |
| `ogcapi-tiles`            | tilesets, tile matrix sets and tile addresses                                              | tiles on a collection   |

The skills follow the API document the tools are generated from: after a
configuration reload, a skill whose operations are gone is no longer
served. Their text never includes values from the configuration, such
as collection names or descriptions. A client that supports the MCP
Skills extension lists them with `skills/list`; any other client reads
the same files as `skill://` resources.

Operators can turn the skills off with `FASTGEOAPI_MCP_SKILLS`; see
[Configuration](../../operators/how-to/enabling-mcp.md#skills-fastgeoapi_mcp_skills).

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
