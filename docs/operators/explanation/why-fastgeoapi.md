---
icon: material/lightbulb-on-outline
---

# :material-lightbulb-on-outline: What fastgeoapi adds to pygeoapi

fastgeoapi is not a fork of [pygeoapi](https://github.com/geopython/pygeoapi).
pygeoapi _is_ the engine: the OGC API implementation, the conformance
declarations, the providers and the HTML templates all come from upstream, and
fastgeoapi tracks its releases. Anything you can serve with pygeoapi you can
serve with fastgeoapi, and the responses are the same.

What differs starts from one question: **your data is already cloud-native, and
something needs a standard API in front of it.** GeoParquet in a bucket, a
PMTiles archive, a COG — formats designed to be read in ranges over HTTP by
clients that know them. An OGC API is what the clients that _don't_ know them
need: QGIS, a browser, a partner's harvester, an agent. The usual way to bridge
the two is a conversion step — load it into PostGIS, cut a tile tree — which
buys the API at the price of a second copy that has to be kept in step.

fastgeoapi serves the API **from the format itself**, where it is. That single
choice decides most of the rest of this page: the providers, the storage layer
they read through, the shape of the request path, and why the configuration is
allowed to live in the same bucket as the data.

| Area                | pygeoapi                                | fastgeoapi                                                            |
| ------------------- | --------------------------------------- | --------------------------------------------------------------------- |
| GeoParquet          | `s3://` via s3fs, no CQL2               | any cloud, full CQL2 pushed down into DuckDB                          |
| Vector tiles        | pre-cut directories, databases, a proxy | PMTiles archives read in place from any cloud, by range               |
| Reads over the wire | every handler on a five-thread executor | ranged reads awaited together; threads left to CPU-bound work         |
| Configuration       | a local file named by `PYGEOAPI_CONFIG` | any object store: S3, GCS, Azure, Tigris, local                       |
| Reconfiguration     | restart the process                     | `POST /admin/config/reload`, atomic swap                              |
| Authentication      | not in scope                            | OIDC/JWT with JWKS, API keys, OPA policies                            |
| AI agents           | —                                       | MCP server over the same API, with its own OAuth authorization server |
| Route table         | every route of every specification      | only the specifications the configuration exposes                     |
| Provider instances  | rebuilt on every request                | reused, with an explicit thread-safety opt-in                         |

The rest of this page explains each line, and links to the how-to guide that
covers it in depth.

## Cloud-native formats are the first-class citizens

A cloud-native geospatial format is one you can read usefully without
downloading it: the bytes are arranged so that a client can ask for the part it
needs. GeoParquet keeps statistics per row group; a PMTiles archive keeps a
directory it can look a tile up in; a COG keeps its tiles addressable. All three
answer the same question — _give me this window_ — in one or a few HTTP range
requests.

pygeoapi can serve some of them, with the shape of an ordinary provider: its
Parquet provider reads `s3://` through s3fs and filters on bbox, datetime and
property equality, and its tile providers expect a directory of pre-cut tiles,
a database, or another tile server to proxy. fastgeoapi treats these formats as
the normal case instead of the special one:

- **What can be a collection.** A GeoParquet file, glob or hive-partitioned
  root; a PMTiles archive of any size. Nothing is converted first, so there is
  no pipeline to run again when the data changes and no second copy to keep in
  step.
- **Where it is read from.** One storage layer for `s3://`, `gs://`, `az://`,
  any S3-compatible endpoint and a local path, with per-dataset region,
  endpoint and anonymous access — because a public bucket and a private one are
  routinely both in the same configuration.
- **What travels.** Filters are pushed down, not applied after the fact: full
  CQL2 including the spatial predicates becomes SQL inside DuckDB, and the
  covering bbox column of GeoParquet 1.1 is used before the exact geometry test.
  The network carries the answer rather than the dataset.
- **What it costs, measured.** A tile from Overture's 18 GB `places.pmtiles` is
  one ranged read once its directory is cached; a bbox query on a 4.47 GB
  GeoParquet dataset read across an ocean is seconds, and 0.9 s once warm beside
  the server. Both figures are in the how-to guides, with the method.

The demo runs the same theme twice on purpose — read where Overture publishes
it, and staged in a bucket in the deployment's own region — because "read it in
place" is a decision with a latency attached, not a slogan.

See [GeoParquet provider](../how-to/geoparquet.md) and
[PMTiles provider](../how-to/pmtiles.md). For a format with no provider yet, the
contributor guide walks a
[Cloud Optimized GeoTIFF](../../contributors/how-to/writing-an-async-provider.md)
from nothing to a working one.

## Security is where fastgeoapi started

Serving data in place only helps if the serving is safe to expose, and this is
the part fastgeoapi was first written for. pygeoapi deliberately leaves
authentication and authorization to the deployment; fastgeoapi fills that gap
with a stack you configure rather than code:

- **OpenID Connect** — OAuth2/JWT bearer tokens validated against the issuer's
  JWKS, with multiple identity providers supported side by side.
- **API keys** — for programmatic clients that cannot run an OAuth flow.
- **Open Policy Agent** — Rego policies decide per-request, so "this tenant may
  read these collections" is a policy change rather than a code change.

The authorization layer wraps the mounted pygeoapi application as ASGI
middleware, which is why it applies uniformly to every route the engine
exposes, including ones added by a future upstream release. Health probes
(`/healthz`, `/readyz`) are mounted outside the protected surface so
orchestrators can reach them without credentials.

## Your OGC API, usable by AI agents

fastgeoapi ships a production [Model Context Protocol](../../consumers/index.md) server at
`/mcp`. An assistant like Claude can list your collections, read their
queryables, run CQL2 queries and execute processes — against the same data,
through the same API, under the same identity a human client would use.

**The tools come from your OpenAPI document.** They are generated by parsing
the OGC API specification the server already publishes, so a collection you add
to the configuration becomes callable without writing a tool definition. There
is no hand-maintained catalogue to drift out of sync.

**There is only one API.** The MCP server reaches pygeoapi in-process over an
`httpx.ASGITransport`, not over the network: no second copy of the engine, no
loopback hop, no internal API key to provision and rotate.

**It is identity-secured, not open.** This is where most "expose an API to an
agent" setups stop, and it is the hard part. The MCP server plays two roles at
once: the protected resource an agent talks to, and its own OAuth
Authorization Server — an OIDC proxy fronting whatever IdP you already run
(Keycloak, Logto, Ory Hydra, Rauthy, Entra…). Concretely it implements:

- OAuth 2.0 Protected Resource Metadata (RFC 9728), advertised in the
  `WWW-Authenticate` challenge, with RFC 6750 error semantics;
- authorization code with PKCE, Authorization Server Metadata (RFC 8414) and
  Dynamic Client Registration (RFC 7591) with redirect-URI validation;
- refresh-token rotation and a client-facing token TTL decoupled from the
  upstream IdP's `expires_in`;
- **CIMD** (Client ID Metadata Document) — not theoretical: Claude identifies
  itself this way against this server in production, including the case of a
  document that declares no `scope`, with an SSRF-hardened fetcher and
  enforcement of the keys and redirect URIs the document publishes;
- mixed-key JWKS validation (RSA/EC/Ed25519), skipping key types it cannot use
  instead of rejecting an entire key set;
- **EMA / ID-JAG** enterprise-managed authorization through the `jwt-bearer`
  grant, currently under end-to-end verification.

**It survives being restarted.** The transport runs in stateless Streamable
HTTP mode, so an auto-suspending machine, a redeploy or a serverless cold start
is transparent to a connected client instead of stranding it on a dead session.

The full standards matrix, with what is verified on a live deployment and what
is still in progress, is in [Supported
specifications](../../consumers/reference/mcp-specifications.md).

## The configuration does not care where it lives

Upstream builds its application at import time: `starlette_app.py` reads
`PYGEOAPI_CONFIG` and `PYGEOAPI_OPENAPI`, opens those local files, and
constructs the API as a module-level side effect. A path is the only thing it
can be given.

fastgeoapi constructs the API programmatically instead — `API(config, openapi)`
from dictionaries it holds in memory — and reaches whatever holds them through
a single storage abstraction. `./pygeoapi-config.yml` and
`s3://tenant-42/pygeoapi-config.yml` are the same call to the same code, and
`gs://`, `az://` and a Tigris bucket are that call too. Nothing anywhere asks
which kind it got.

That is the claim worth making, and it is stronger than "it can read a bucket":
there is no bucket path and local path to keep in step, no branch to forget on
one side. It is also why the end-to-end tests run against a real S3 rather than
a stand-in — if a local directory and a remote prefix are one code path, the
one worth exercising is the one that signs requests.

What it buys, in order of how often it matters:

- **the file stays where it belongs** — beside the deployment, in a bucket, or
  on the developer's disk, without the choice reaching the code;
- **read-only filesystems work** (AWS Lambda, distroless containers), where
  writing a YAML file next to the process is not an option;
- **each tenant gets its own configuration object** without re-templating an
  environment variable.

See [Config from cloud storage](../how-to/cloud-config.md).

## Reload without a restart

Because the API is an object rather than an import side effect, fastgeoapi can
build a second one and swap it in atomically. `POST /admin/config/reload`
returns `202` immediately, rebuilds in the background, and `GET` on the same
route reports the outcome of the last attempt. It is protected by the same
authentication as the rest of the API — security follows the configuration,
so there is no second credential to manage. Reloads are idempotent on the
configuration object's ETag, so a webhook that fires twice does the work once.

The MCP tools follow too: they are regenerated from the new OpenAPI document,
so a collection added to the configuration becomes callable by an agent
without restarting anything. A client that is already connected keeps its
cached list until it asks again, normally on reconnect.

One limit is worth knowing up front: in a multi-instance deployment the
reload reaches only the instance that received the call.

## Only the routes your configuration actually needs

pygeoapi registers the full route table of every specification it implements —
Features, Tiles, EDR, Processes, STAC, Records — whether or not your
configuration has a resource behind them. fastgeoapi groups the route table by
specification and mounts a group only when the configuration exposes a
provider for it, recomputing the set on every reload.

The result is an OpenAPI document and a route table that describe what the
server can really do. `/conformance` is filtered the same way, from the
configured providers rather than from a static list. A parity test keeps the
_complete_ table aligned with upstream's, so a route added in a new pygeoapi
release turns the suite red instead of silently disappearing.

## GeoParquet from any cloud, with CQL2 in the engine

Upstream ships a Parquet provider built on pyarrow and geopandas. It reads
`s3://` through s3fs — other cloud schemes fall back to pyarrow's
auto-detection, with nowhere to pass a region, an endpoint or anonymous
credentials — and it filters on bbox, datetime and property equality. There is
no CQL2.

fastgeoapi's GeoParquet provider runs on DuckDB with the `spatial` extension:

- **Any object store**, with credentials, region, custom endpoint and
  public-bucket access as provider options.
- **Full CQL2**, text and JSON, translated to SQL and pushed into the engine —
  spatial predicates included. `S_INTERSECTS` is evaluated by DuckDB, not
  post-filtered in Python.
- **GeoParquet 1.1 covering bbox** columns used as a pre-filter before the
  exact geometry test, plus hive-partition and row-group pruning.
- **DuckDB's native cloud reader**, which caches the blocks it fetches. On
  Overture's `division-areas` (4.47 GB across eight files, read from Europe)
  a bbox query over Lazio went from **44 s to 0.9 s** once warm.
- No geopandas, shapely or pyarrow on the serving path.

The provider is synchronous — DuckDB has no async API and pygeoapi's provider
contract is synchronous — but it does not block the event loop: the factory's
shim dispatches provider calls to an executor.

See [GeoParquet provider](../how-to/geoparquet.md).

## Vector tiles from an archive, awaited

Upstream serves vector tiles from a directory of pre-cut files, from
Elasticsearch or PostgreSQL, or by proxying another tile server. A
[PMTiles](https://github.com/protomaps/PMTiles) archive — one file, any
size, read by byte range — has no provider there.

fastgeoapi's PMTiles provider reads the archive where it lives, on a local
path or any object store, through the same storage layer the configuration
uses. Overture Maps' 18 GB `places.pmtiles` is served in place, with no copy.
It is also the first provider written on fastgeoapi's asynchronous provider
pattern: the tile route awaits it, so one process keeps many tiles in flight
instead of parking a thread on each ranged read, and a cold burst of
identical requests shares its reads instead of repeating them. The same
class still honours pygeoapi's synchronous contract for everything else.

See [PMTiles provider](../how-to/pmtiles.md).

## Async where waiting is the cost, threads where work is

Serving a cloud-native format means reading it in ranges over the network, and
that changes what the request path should look like.

pygeoapi's handlers all run through the default executor, which Python sizes at
`min(32, cpu_count + 4)` — **five threads** on the single-vCPU machine the demo
runs on. Five requests waiting on a round trip, and the sixth is queued no
matter what it asked for. A map view asks for twenty to fifty tiles at once, and
each tile is one to three ranged reads: exactly the shape that a thread pool
serves worst and an event loop serves best.

So fastgeoapi does not make everything asynchronous. It makes **the waiting**
asynchronous:

- **One awaited route.** Tile data is served on the loop when the collection's
  provider declares it can be. It sits in the same route table, behind the same
  authentication, and falls back to pygeoapi's handler — byte for byte — for a
  provider that does not.
- **A second face, not a replacement.** A provider gains an asynchronous twin of
  a method and keeps the synchronous one, so pygeoapi's own chain, the CLI and
  the dry run go on using it unchanged.
- **One implementation behind both.** The logic that parses an archive is
  written as a generator that asks for byte ranges and is fed by two drivers,
  one blocking and one awaiting. There is no second copy of the parsing to keep
  correct.
- **Reads that de-duplicate themselves.** Identical ranges in flight share one
  request: a cold burst of fifty tiles went from **245 ranged reads to 54**,
  fewer than the thread pool made.
- **Proof rather than intent.** The test suite runs with a guard that fails any
  test which blocks the loop, so "this is async" is a property that gets
  checked.

Measured on the demo, twenty vector tiles that take **8–11 s** one at a time
come back in **1.7–2.6 s** with eight awaited together, on one vCPU.

And where the cost is not waiting, nothing changes: DuckDB scanning a GeoParquet
dataset is CPU-bound work, a thread is where work belongs, and awaiting it would
change the syntax and nothing else.

The design and its reasoning are in
[Two faces for a provider](../../contributors/explanation/async-providers.md);
[Writing an async provider](../../contributors/how-to/writing-an-async-provider.md)
builds one.

## Provider instances are reused

`pygeoapi.plugin.load_plugin` constructs a fresh object on every call, so every
request pays for whatever the provider does in `__init__`. For a DuckDB-backed
provider that is 76 ms of connection and extension setup against 2.9 ms of
actual query.

fastgeoapi adds a cache in front of `load_plugin`, keyed on the provider
definition. The opt-in is explicit and provider-agnostic: a class that declares
`THREAD_SAFE = True` is shared process-wide, anything else is cached per
thread, because upstream hands every request a fresh instance and a provider is
entitled to rely on that. A generation counter invalidates the cache whenever
the API is rebuilt. Measured end to end, HTTP latency dropped from 73 ms to
24 ms.

## An OpenAPI document a client can consume

fastgeoapi resolves the external `$ref`s in the generated document
deterministically, so the schema a client downloads today is the schema it
downloads tomorrow, and augments it with the security schemes that match the
configured authentication. Server URLs follow the reverse proxy the deployment
sits behind rather than the port the process happens to bind. The document is
validated in CI with Spectral, exercised with contract tests, and scanned with
OWASP ZAP.

The same document can be generated offline with the `fastgeoapi` CLI and
written back to the object store, so a deployment can serve a pre-built
artifact instead of computing it at boot.

## What we aim to send upstream

Several of the items above started as bugs or gaps found while building
fastgeoapi, and would serve pygeoapi users beyond this project. They are
candidates for upstream contribution, not commitments — this list is updated as
each one is actually proposed:

- [ ] Plugin instance cache with an explicit `THREAD_SAFE` opt-in, so providers
      are not rebuilt on every request.
- [ ] SQL escaping in pygeofilter's `sql` backend: literals and `LIKE` patterns
      are interpolated unescaped today.
- [ ] Cache invalidation for the localized configuration, so a rebuilt API does
      not serve stale HTML.
- [ ] The HTML templates read `server.limits`, which the configuration schema
      does not require — either the schema or the template should give way.
- [ ] An application-factory RFC: building the API without import-time
      environment variables.
- [ ] A PMTiles tile provider, without the storage layer it depends on here.
