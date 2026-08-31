# Consuming

You are calling fastgeoapi rather than running it — from an application,
a script, or an AI agent.

There are two ways in, and they are the same data. **OGC API** over
HTTP, which any standards-aware client already speaks. And **MCP**,
which presents the same collections as tools an agent can call, with
authorization of its own.

<div class="grid cards" markdown>

- :material-school: **[Tutorials](tutorials/connecting-an-mcp-client.md)**

  Learning-oriented. Connect a client and call your first tool.

- :material-wrench: **[How-to guides](how-to/mcp-inspector.md)**

  Task-oriented. Verifying what a server is really exposing.

- :material-book-open-variant: **[Reference](reference/openapi.md)**

  Information-oriented. The OpenAPI document the demo serves, and the
  MCP specifications this implements.

- :material-lightbulb: **[Explanation](explanation/mcp-server.md)**

  Understanding-oriented. What the MCP server is, how it authorizes,
  and why it is built the way it is.

</div>

## If you only speak OGC API

Nothing here is required. The server is a standard OGC API — Features
implementation and behaves like one; point your client at the landing
page and follow the links. The [OpenAPI
document](reference/openapi.md) describes everything it serves,
including the security schemes, which is what tells your client how to
authenticate.
