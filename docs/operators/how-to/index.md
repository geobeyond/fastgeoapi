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

### The demo's own configuration, and where to read it

The public demo is not configured by a document you have to take on
trust. The same one lives in three places, deliberately:

| Where                                        | What it is for                      |
| -------------------------------------------- | ----------------------------------- |
| `pygeoapi-config.demo.yml` in the repository | history, review, and a way back     |
| [the object the deployment reads][live]      | what is actually serving, right now |
| `DEV_PYGEOAPI_CONFIG` in `.flyio.env`        | the name of that object             |

[live]: https://fastgeoapi-demo.fly.storage.tigris.dev/pygeoapi-config.demo.yml

The object carries the same name as the file, so there is nothing to
translate between the two.

The first two are kept equal. Fetch the second and diff it against the
first: if they differ, the repository is behind, and that is worth
knowing rather than guessing.

```bash
curl -s https://fastgeoapi-demo.fly.storage.tigris.dev/pygeoapi-config.demo.yml \
  | diff - pygeoapi-config.demo.yml && echo "in step"
```

**You can run it.** Every dataset it names is readable without
credentials — Overture Maps' own public releases, and the two extracts of
ours on the same bucket, opened for reading so the demo can be reproduced
rather than believed:

```bash
pip install 'fastgeoapi[geoparquet,pmtiles]'
PYGEOAPI_CONFIG=pygeoapi-config.demo.yml fastgeoapi run
```

The default `pygeoapi-config.yml` is left alone on purpose: it is what a
plain `pip install fastgeoapi` starts with and what the published image
carries, so it may only name providers an installation without extras can
build.

!!! warning "A demo is not a deployment"

    That bucket is readable by anyone because the point here is to be
    checked. **In production, keep the configuration private.** It names
    the buckets it reads, and those may hold data you mean to offer only
    through the API — as OGC API - Features and Tiles, with your
    authentication in front — rather than as files anyone can fetch. The
    document holds no credentials either way: every provider takes its
    keys from the environment.

    Writing it stays authenticated in both cases. The bucket grants read
    to everyone and write to nobody, so the way to change the demo's
    configuration is the same as yours: the
    [editor](configuration-editor.md), pointed at the object.

Two things to expect the first time, both measured rather than guessed:

- **The GeoParquet collections are what make the boot slow.** The
  provider reads the dataset's schema when it is constructed — at boot,
  on every configuration reload and on every dry run. Measured from
  Europe with a warm DuckDB extension cache the whole server was
  answering in **40 s**; constructing the Overture one alone, cold, took
  **87 s**. In the same region it is a fraction of either. The server
  looks hung and is not; [staging a regional
  extract](geoparquet.md#staging-an-overture-extract) is the cure, and
  the `lazio-roads` pair is that cure measured.
- **The tile collections cost nothing to start.** Overture's archive
  holds **zoom 14 only**, which is their choice rather than ours, so its
  `extents.bbox` is pinned to a city and the built-in map opens where
  there are tiles; [the PMTiles
  guide](pmtiles.md#performance-what-a-tile-costs) explains why a global
  box would open on an empty map.

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
