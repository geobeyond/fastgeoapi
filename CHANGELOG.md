## v0.4.0 (2026-10-14)

### BREAKING CHANGES

- **tiles**: the vector TileJSON follows TileJSON 3.0.0 as MapLibre reads it. `tiles` lists `{z}/{y}/{x}` URL templates (they were `{tileMatrix}/{tileRow}/{tileCol}`), `bounds` and `center` are arrays (they were comma-separated strings), and each entry of `vector_layers` has `id` and `fields`, with its other keys only when they are known.
- **tiles**: `minzoom` and `maxzoom` in every TileJSON are the zooms of the data within the provider's `zoom` option (they were the archive's), and the zoom of `center` stays between them.

### Notes

- **html**: native HTML pages replace pygeoapi's templates when `FASTGEOAPI_HTML_PAGES=native` is set and the `fastgeoapi[html]` extra is installed, which brings the new `fastgeoapi-html` package; pygeoapi's pages stay the default. Their maps open on the data, then on the collection's `view`, then on its extent.
- **mcp**: the authorization server metadata names `token_endpoint_auth_signing_alg_values_supported: ["RS256"]`, the one algorithm it accepts for `private_key_jwt` client assertions, and OIDC discovery is also served under the issuer, at `/mcp/.well-known/openid-configuration`. Each refused token request leaves one log line with the assertion's header and claims.

### Features

- **html**: widen a map across its page and narrow it back
- **html**: give every map the labels of a control that widens it
- **html**: name the service's OGC APIs over the landing title
- **html**: set every size of the pages from a variable, large or dense
- **html**: open the pages with a map on their first block beside a square map
- **html**: draw the maps on a MapLibre style given as server.map.style
- **html**: draw the basemap under the tiles, as pygeoapi does
- **html**: turn maps with two fingers on a trackpad and keep map images flat
- **html**: show the duration, message and parameters of jobs and page through them
- **html**: state what pygeoapi's landing, collections, schema and queryables pages state
- **html**: show the tilt on the compass and add a scale bar to every map
- **html**: describe the STAC entries, collections and assets as pygeoapi does
- **html**: list every property of the items and show item values as pygeoapi does
- **html**: show the license, CRS, EDR parameters and tileset metadata, as pygeoapi does
- **html**: open every map with its attribution folded
- **html**: list every link of the JSON, as pygeoapi's pages do
- **html**: give every map its zoom buttons
- **html**: add the STAC pages with the assets and footprint of an item
- **html**: add the EDR pages with the query form, its tables and its map
- **html**: add the coverage page with its grid, bands and downloads
- **html**: add the item page with its properties, map and JSON-LD
- **html**: add the items page with the parameters its data applies
- **html**: know which item parameters each data source applies
- **html**: add the tileset pages with their template, TileJSON and map
- **html**: add the collection page and preview its data on a map
- **html**: draw tiles, map images, features and extents in a MapLibre island
- **html**: decide what a page's map shows first
- **html**: let a page read related routes and show a refused parameter again
- **html**: add the job pages and follow a running job
- **html**: add the process pages and run a process from its page
- **html**: show the API documentation with Swagger UI or ReDoc
- **html**: add the collections, queryables and schema pages
- **html**: add the conformance and tile matrix set pages
- **html**: build the stylesheet and the islands of the pages with Vite
- **html**: serve fastgeoapi's landing page when the settings ask for native pages
- **html**: render a route's page from the returned JSON
- **html**: read the page catalogs and the compiled assets
- **tiles**: pick the style a page draws a collection's tiles with
- **config**: accept a view for the maps of each collection
- **tiles**: publish the vector TileJSON in the shape MapLibre reads
- **maps**: answer a map with its ETag, and 304 when the client has it
- **maps**: tell which version of a map would be drawn, without drawing it
- **tiles**: answer a tile with its ETag, and 304 when the client has it
- **tiles**: tell which version of the archive a tile would come from
- **cache**: add the HTTP cache policy for maps and tiles
- **maps**: draw elevation archives as a hillshade
- **pmtiles**: serve raster archives as map or elevation tilesets
- **pmtiles**: tell what a tile type allows and how wide its tiles are
- **tiles**: add the contract with tile backends and their registry
- **maps**: let the renderer read remote archives through the loopback server
- **storage**: serve cached ranges on loopback
- **pmtiles**: read remote archives through the range cach
- **storage**: configure the range cache and hand it to the providers
- **storage**: read ranges of one version of an object through the cache
- **storage**: keep byte ranges in an object store under a cap
- **storage**: list with metadata, delete and read a range of one version
- **maps**: choose the map styles with the style_factory option
- **maps**: choose map sources from a registry and style them by their content
- **demo**: draw the Lazio roads as a map and document the provider
- **maps**: draw maps with one MapLibre Native process per provider
- **mcp**: return the map of a collection to the client as an image
- **maps**: serve /map from a native provider awaited on the loop
- **maps**: add the map contracts, the camera, a source and its styles

### Fixes

- **types**: annotate @contextmanager functions as Generator
- **mcp**: serve OIDC discovery under the issuer path
- **html**: keep a basemap style that arrives in time while its tiles load slowly
- **html**: drop a link from the data that urlsplit cannot read
- **mcp**: answer and log a token request whose assertion nests too deep
- **mcp**: log only why fastmcp refuses a client assertion, on one line
- **mcp**: escape and bound what a refused token request writes to the log
- **mcp**: log why a token request is refused
- **mcp**: name the signing algorithms of private_key_jwt in the server metadata
- **tiles**: leave out a style file that reads but is no style
- **tiles**: publish in the TileJSON the zooms a client can ask
- **editor**: check fastgeoapi's own keys when validating and saving
- **html**: draw on the basemap's tiles when its style is no style or late
- **html**: ask the image of a turned map at the size of its box
- **html**: turn and zoom with a trackpad without fighting MapLibre's touch
- **html**: open data maps on their data, view or extent from the start
- **html**: return how many items match when only the count is asked
- **html**: draw items asked in another crs from their JSON in CRS84
- **html**: offer crs where pygeoapi transforms the output of the data
- **html**: name the variable that turns the native pages on with its prefix
- **html**: show small cell sizes with their decimals
- **html**: leave hidden collections and absent processes off the landing
- **proxy**: rewrite native pages and the Link header for the forwarded host
- **html**: keep the page when a related route raises, and encode its URLs
- **html**: never turn a javascript: or data: URL from the data into a link
- **html**: open on the extent when the tiles' center is at zoom 0
- **html**: draw the item under the pointer above overlapping points
- **html**: load the MapLibre worker and stop fitting at street level
- **cache**: keep gzip bodies stable, log failures by type, and 304 maps only as PNG
- **geoparquet**: import duckdb only when a query runs
- **geoparquet**: answer 504 when the store does not answer in time
- **collections**: describe the items from the provider that serves them
- **tiles**: explain refusals on metadata routes and draw raster tilesets
- **conformance**: declare png and jpeg tiles, and mvt only when some tiles are vector
- **pmtiles**: refuse an archive whose tiles do not match the configured format
- **deps**: bump pyjwt and fix its latest cve
- **storage**: strip http store prefix urls
- **maps**: cut the loopback token from renderer errors
- **maps**: keep serving the ranges of a map in flight through a reload
- **storage**: let the range cache sweep only its own entries
- **maps**: read each style at its first map and check default_style
- **maps**: replace a renderer process found dead before the map
- **maps**: keep maps drawing behind OPA and the reverse proxy
- **maps**: raise the size limit, answer 413 and free the queue on disconnect
- **maps**: keep the camera within the zooms and the world renderers take
- **reload**: report a reload as applied once the artifact is written
- **tiles**: answer a tileset in JSON when the request asks for no format

### Performance

- **maps**: draw at the known archive version while it is revalidated
- **geoparquet**: read a bucket dataset's schema once per version of its objects

### Refactoring

- **tiles**: serve tiles from a generic provider composed with a PMTiles source
- **maps**: name the map options data_url and style_source
- **maps**: compose the map provider from a render queue and shared parts

## v0.3.0 (2026-09-27)

### Features

- **mcp**: give the tileset tools names that FastMCP does not cut
- **mcp**: annotate the generated tools and title them from the summaries
- **mcp**: report the fastgeoapi version, the API address and instructions

### Fixes

- **openapi**: describe the tileset list with the OGC response
- **deps**: require fastmcp 4.0.10 for the ID-JAG token fix
- **openapi**: allow unlocated features and drop CQL2 where nothing filters
- **openapi**: make two generated tool schemas match what the server does

## v0.2.0 (2026-09-22)

### Features

- **reload**: every worker converges to the configuration source

### Refactoring

- **reload**: fold the poller into ReloadManager and inject the instance id

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
