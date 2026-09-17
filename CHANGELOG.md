## v0.1.1 (2026-09-17)

### Features

- **ci**: say which classes the standards publish and this server does not

### Fixes

- **ci**: the conformance validator belongs in the sessions that run it
- **openapi**: describe the tileset the server already answers
- **conformance**: declare writes only where something is writable

## v0.1.0 (2026-09-16)

### Features

- **demo**: the demo's configuration, sync with the repository and readable
- **mcp**: binary tiles are not tools
- **pmtiles**: a natively async tile provider over a PMTiles archive
- **storage**: identical awaited reads in flight share one fetch
- **provider**: GeoParquet carries the async mixin, and stays honest about DuckDB
- **storage**: hand the obstore object and the key to libraries that read through it
- **tiles**: await a native provider on the tile data route, threadpool for the rest
- **provider**: a sans-I/O core driven by two ten-line drivers
- **provider**: byte ranges bound to a provider's data object
- **storage**: byte-range reads, sync and async, through the object store
- **interfaces**: async capability Protocols for tile and feature providers
- **provider**: the async part beside pygeoapi's contract, as a mixin and a view
- **mcp**: serve a SEP-2127 server card at mcp server card well-known endpoint
- **editor**: augmented option, what only fastgeoapi can tell you
- **editor**: two views of one document, both editable
- **editor**: a page that mirrors the four endpoints
- **editor**: serve the page from the authoring role only
- **editor**: hand the token over in a cookie
- **editor**: bridge the form to the document without owning it
- **cli**: open the editor without putting the secret in a URL
- **editor**: the endpoints, and one rule they exist to respect
- **editor**: the authoring role, which cannot activate anything
- **editor**: tell an operator what a configuration will do
- **config**: draft the changelog entry from the schema diff
- **docs**: generate the configuration reference from the schema
- **config**: check the generated models in CI
- **config**: stable names in front of the generated models
- **config**: generate the pygeoapi configuration models
- **config**: generate the pygeoapi configuration models
- **config**: refuse a configuration that does not match the schema
- **mcp**: regenerate the tools when the configuration changes
- **demo**: serve two overture collections with the config in a bucket
- **scripts**: stage an overture extract as cloud-ready geoparquet
- **provider**: serve GeoParquet collections end to end
- **provider**: compile CQL2 into DuckDB spatial SQL
- **provider**: DuckDB session for local and cloud GeoParquet sources
- **storage**: write the openapi artifact through the storage protocol
- **pygeoapi**: mount only the spec groups the config exposes
- **cli**: generate the openapi document from the storage source
- **app**: wire the programmatic pygeoapi behind the holder and add the reload webhook
- **pygeoapi**: programmatic sub-app factory, route parity test and holder
- **config**: load the pygeoapi config from any storage source
- **storage**: object-store layer with protocol, obstore backend and sync/async bridge
- **mcp**: accept enterprise ID-JAG assertions according to EMA - SEP-990
- **mcp**: migrate to early FastMCP 4 and drop three local workarounds

### Fixes

- **openapi**: declare only the tags an operation uses
- **geoparquet**: prove the datetime is one before it becomes a literal
- **readme**: dead links
- **auth**: a 401 has to say how to authenticate
- **editor**: the form may not write what the document does not say
- **image**: take the distribution's updates in the runtime layer
- **storage**: an explicit endpoint wins over the environment
- **pmtiles**: a literal URL template is a 404, not a 500
- **tests**: sanitise the job id instead of testing a literal
- **openapi**: hoist remote-local references instead of leaving them dangling
- **mcp**: the server card must never take the service down
- **frontend**: stop .gitignore from swallowing a source directory
- **cli**: let the editor run for someone who only has pygeoapi
- **editor**: check a data source the way the provider reads it
- **storage**: translate store options into obstore's vocabulary
- **config**: stop refusing a configuration that works
- **ci**: stop reformatting the generated reference page
- **ci**: stop shipping the demo's configuration as the default
- **mcp**: hand FastMCP the client it expects
- **provider**: keep a dataset's read path out of the environment
- **provider**: mark the reviewed SQL sites for bandit
- **ci**: type-check against the optional extras
- **provider**: enumerate cloud datasets instead of globbing them
- **provider**: make the DuckDB session usable on a read-only runtime
- **deps**: name fastmcp-slim explicitly so the unlocked lane resolves
- **ci**: satisfy ruff on the OWASP gate script
- **ci**: make the OWASP check actually run, and fail when it cannot
- **mcp**: read the client identity from the initialize message
- **ci**: resolve dependencies from the lock for pull requests into develop
- **mcp**: filter probe access logs and improve the empty-tool-list failure management
- **fly**: keep one demo machine warm and declare health checks
- **mcp**: keep the full scope set available to CIMD clients

### Performance

- **provider**: let duckdb read cloud data with its own reader
- **pygeoapi**: reuse plugin instances instead of rebuilding them per request

## v0.0.12 (2026-08-04)

### Features

- **mcp**: CIMD end-to-end coverage and private_key_jwt audience fix

### Fixes

- **openapi**: correct queryables schema at the generation source

## v0.0.11 (2026-08-04)

### Features

- **mcp**: upgrade fastmcp to 3.4.5
- **image**: hardened multi-stage image with scan-gated GHCR publish
- **ops**: add health probes and relocatable schema cache
- **mcp**: fail-closed auth guard with explicit passthrough opt-in

### Fixes

- **pygeoapi**: safeguard datetime values return 400 instead of crashing
- **ci**: evict safety from the dev group, install it pinned in its nox virtual environment
- **ci**: pin compatible typer in the safety tool venv
- **image**: address security review findings on the hardened image
- **ci**: pin an existing trivy-action version

## v0.0.10 (2026-08-02)

### Fixes

- **ci**: disable nltk import guard for the safety session

### Refactoring

- **auth**: drop the mcpauth dependency

## v0.0.9 (2026-08-01)

### Features

- **ops**: persist MCP OAuth storage on a fly volume
- **mcp**: decouple client access-token TTL from IdP expires_in
- **mcp**: remember consent

### Fixes

- **ci**: tag releases when the version tag is missing
- **mcp**: run streamable HTTP in stateless mode
- **docker**: install production dependencies from uv lock file
- **ci**: pin joserfc<1.7 to not break the IdP test on unlocked installs
- **security**: restrict FORWARDED_ALLOW_IPS to the Fly proxy network
- **mcp**: serve slash-less /mcp and discovery URLs without redirects
- **security**: default prod consent mode to remember in .env template
- **tests**: pin consent mode in MCP OAuth e2e fixture
- **tests**: correct CRLF sanitization in openapi contract tests
- **deps**: update dependency cachetools to v7 (#383)
- **deps**: update dependency geoalchemy2 to >=0.18.1,<0.19 (#349)
- **deps**: update dependency cachetools to v6 (#368)

### Refactoring

- **mcp**: migrate to fastmcp 3.x with ASGITransport and native forward_resource (#409)
- handle issuer and audience validation of oauth2 tokens
- handle issuer and audience validation of oauth2 tokens
- handle issuer and audience validation of oauth2 tokens
- handle issuer and audience validation of oauth2 tokens

## v0.0.8 (2025-12-29)

## v0.0.7 (2025-12-22)

## v0.0.6 (2025-12-19)

## v0.0.5 (2025-12-18)

## v0.0.4 (2025-12-11)

### Fixes

- **pyproject.toml**: Fix backend dependency for pygeofilter
- **pyproject.toml**: Fix backend dependency for pygeofilter
- **cli**: Fix openapi generation
- **pyproject.toml**: Fix backend dependency for pygeofilter

## v0.0.1 (2023-12-26)
