---
icon: material/wrench
---

# :material-wrench: How-to Guides

This section contains practical guides for configuring and using fastgeoapi features.

## Serve a cloud-native format as a collection

The two providers fastgeoapi adds read their data where it already is, with no conversion step in between:

- [**GeoParquet**](geoparquet.md) — a file, a glob or a hive-partitioned root as an OGC API - Features collection, with CQL2 pushed down into DuckDB.
- [**PMTiles**](pmtiles.md) — one archive of any size as an OGC API - Tiles collection, read by byte range and awaited.

Both take their bucket settings per dataset, and [the configuration itself](cloud-config.md) can live in the same place. For a format with no provider yet, the contributor guide walks a [Cloud Optimized GeoTIFF](../../contributors/how-to/writing-an-async-provider.md) from nothing to a working one.

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
- **Streamable HTTP Transport**, stateless, with the protocol version negotiated per connection

For complete configuration instructions, the supported specifications matrix, and usage examples, see the dedicated [MCP section](../../consumers/index.md).
