---
icon: material/format-list-bulleted-type
---

# :material-format-list-bulleted-type: Configuration reference

Every key fastgeoapi accepts in the pygeoapi configuration document.

!!! info "Where this comes from"

    The tables below are generated from pygeoapi 0.24.0's own
    configuration schema, descriptions included — that text is
    pygeoapi's, published under the MIT licence. Regenerate with
    `nox -s models`.

## `server`

server object

| Key                                | Type                 | Required | Description                                                                                                                                                       |
| ---------------------------------- | -------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `server.bind`                      | object               | yes      | binding server information                                                                                                                                        |
| `server.bind.host`                 | string               |          | binding IP                                                                                                                                                        |
| `server.bind.port`                 | integer              |          | binding port                                                                                                                                                      |
| `server.url`                       | string               | yes      | URL of server (as used by client)                                                                                                                                 |
| `server.icon`                      | string               |          | URL of favicon for default HTML customization                                                                                                                     |
| `server.logo`                      | string               |          | URL of logo image for default HTML customization                                                                                                                  |
| `server.admin`                     | boolean              |          | whether to enable the Admin API (default is false)                                                                                                                |
| `server.mimetype`                  | string               | yes      | default MIME type                                                                                                                                                 |
| `server.encoding`                  | string               | yes      | default server encoding                                                                                                                                           |
| `server.gzip`                      | boolean              |          | default server config to gzip/compress responses to requests with gzip in the Accept-Encoding header                                                              |
| `server.language`                  | string               |          | default server language                                                                                                                                           |
| `server.languages`                 | array                |          | supported languages                                                                                                                                               |
| `server.locale_dir`                | string               |          | directory of translations                                                                                                                                         |
| `server.cors`                      | boolean              |          | boolean on whether server should support CORS                                                                                                                     |
| `server.pretty_print`              | boolean              |          | whether JSON responses should be pretty-printed                                                                                                                   |
| `server.limit`                     | integer              |          | limit of items to return. DEPRECATED: use limits instead                                                                                                          |
| `server.limits`                    | object               |          | server level data limiting                                                                                                                                        |
| `server.limits.max_items`          | integer              |          | maximum limit of items to return for item type providers                                                                                                          |
| `server.limits.default_items`      | integer              |          | default limit of items to return for item type providers                                                                                                          |
| `server.limits.max_distance_x`     | number               |          | maximum distance in x for all data providers                                                                                                                      |
| `server.limits.max_distance_y`     | number               |          | maximum distance in y for all data providers                                                                                                                      |
| `server.limits.max_distance_units` | string               |          | maximum distance units as per UCUM https://ucum.org/ucum#section-Tables-of-Terminal-Symbols                                                                       |
| `server.limits.on_exceed`          | string               |          | how to handle limit exceeding                                                                                                                                     |
| `server.templates`                 | object               |          | optional configuration to specify a different set of templates for HTML pages. Recommend using absolute paths. Omit this to use the default provided templates    |
| `server.templates.path`            | string               |          | path to templates folder containing the Jinja2 template HTML files                                                                                                |
| `server.templates.static`          | string               |          | path to static folder containing css, js, images and other static files referenced by the template                                                                |
| `server.map`                       | object               | yes      | leaflet map setup for HTML pages                                                                                                                                  |
| `server.map.url`                   | string               |          | URI template of tile server                                                                                                                                       |
| `server.map.attribution`           | string               |          | map attribution                                                                                                                                                   |
| `server.ogc_schemas_location`      | string               |          | local copy of http://schemas.opengis.net                                                                                                                          |
| `server.manager`                   | object               |          | optional OGC API - Processes asynchronous job management                                                                                                          |
| `server.manager.name`              | string               |          | plugin name (see `pygeoapi.plugin` for supported process_managers)                                                                                                |
| `server.manager.connection`        | ['string', 'object'] |          | connection info to store jobs (e.g. filepath)                                                                                                                     |
| `server.manager.output_dir`        | string               |          | temporary file area for storing job results (files)                                                                                                               |
| `server.api_rules`                 | object               |          | optional API design rules to which pygeoapi should adhere                                                                                                         |
| `server.api_rules.api_version`     | string               |          | optional semantic API version number override                                                                                                                     |
| `server.api_rules.strict_slashes`  | boolean              |          | whether trailing slashes are allowed in URLs (disallow = True)                                                                                                    |
| `server.api_rules.url_prefix`      | string               |          | Set to include a prefix in the URL path (e.g. https://base.com/my_prefix/endpoint). Please refer to the configuration section of the documentation for more info. |
| `server.api_rules.version_header`  | string               |          | API version response header (leave empty or unset to omit this header)                                                                                            |

## `pubsub`

Pub/Sub settings for event driven notifications

| Key                     | Type    | Required | Description                                  |
| ----------------------- | ------- | -------- | -------------------------------------------- |
| `pubsub.name`           | string  | yes      | name of pubsub client                        |
| `pubsub.broker`         | object  | yes      | broker definition                            |
| `pubsub.broker.url`     | string  |          | URL of broker                                |
| `pubsub.broker.channel` | string  |          | channel to subscribe to                      |
| `pubsub.broker.hidden`  | boolean |          | whether to hide broker link on API responses |

## `logging`

logging definitions

| Key                             | Type    | Required | Description                                                                                                                                                                             |
| ------------------------------- | ------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `logging.level`                 | string  | yes      | The logging level (see https://docs.python.org/3/library/logging.html#logging-levels). If level is defined and logfile is undefined, logging messages are output to the server’s stdout |
| `logging.logfile`               | string  |          | the full file path to the logfile.                                                                                                                                                      |
| `logging.logformat`             | string  |          | custom logging format                                                                                                                                                                   |
| `logging.dateformat`            | string  |          | custom date format to use in logs                                                                                                                                                       |
| `logging.rotation`              | object  |          | log rotation settings                                                                                                                                                                   |
| `logging.rotation.mode`         | string  |          | whether to rotate based on size or time                                                                                                                                                 |
| `logging.rotation.when`         | string  |          | type of interval                                                                                                                                                                        |
| `logging.rotation.interval`     | integer |          | how often to rotate in time mode                                                                                                                                                        |
| `logging.rotation.max_bytes`    | integer |          | when to rotate in size mode                                                                                                                                                             |
| `logging.rotation.backup_count` | integer |          | how many backups to keep                                                                                                                                                                |

## `metadata`

server metadata

| Key                                        | Type   | Required | Description                                                   |
| ------------------------------------------ | ------ | -------- | ------------------------------------------------------------- |
| `metadata.identification`                  | object | yes      | server identification                                         |
| `metadata.identification.title`            |        |          | the title of the service                                      |
| `metadata.identification.description`      |        |          | some descriptive text about the service                       |
| `metadata.identification.keywords`         |        |          | list of keywords about the service                            |
| `metadata.identification.keywords_type`    | string |          | keyword type as per the ISO 19115 MD_KeywordTypeCode codelist |
| `metadata.identification.terms_of_service` |        |          | terms of service                                              |
| `metadata.identification.url`              | string |          | informative URL about the service                             |
| `metadata.license`                         | object | yes      | licensing details                                             |
| `metadata.license.name`                    |        |          | licensing details                                             |
| `metadata.license.url`                     |        |          | license URL                                                   |
| `metadata.provider`                        | object | yes      | service provider details                                      |
| `metadata.provider.name`                   |        |          | organization name                                             |
| `metadata.provider.url`                    |        |          | URL of provider                                               |
| `metadata.contact`                         | object | yes      | service contact details                                       |
| `metadata.contact.name`                    | string |          | Lastname, Firstname                                           |
| `metadata.contact.position`                | string |          | position                                                      |
| `metadata.contact.address`                 | string |          | postal address                                                |
| `metadata.contact.city`                    | string |          | city                                                          |
| `metadata.contact.stateorprovince`         | string |          | administrative area                                           |
| `metadata.contact.postalcode`              | string |          | postal or ZIP code                                            |
| `metadata.contact.country`                 | string |          | country                                                       |
| `metadata.contact.phone`                   | string |          | phone number                                                  |
| `metadata.contact.fax`                     | string |          | fax number                                                    |
| `metadata.contact.email`                   | string |          | email address                                                 |
| `metadata.contact.url`                     | string |          | URL of contact                                                |
| `metadata.contact.hours`                   | string |          | hours of service                                              |
| `metadata.contact.instructions`            | string |          | contact instructions                                          |
| `metadata.contact.role`                    | string |          | role as per the ISO 19115 CI_RoleCode codelist                |

## `resources`

collections or processes published by the server

_No documented keys._

## fastgeoapi additions

The keys below are **not in pygeoapi's schema**. They are read by
fastgeoapi's own providers, and they pass validation because the schema
declares no `additionalProperties` — which also means nothing upstream
documents them. This section is hand-written and is never touched by the
generator.

Being outside the schema has one practical consequence: the
[configuration editor](../how-to/configuration-editor.md)'s form cannot create
the provider keys below, because no widget can be generated for a key the
schema does not mention. It preserves them faithfully once they exist; to
write one, use the editor's YAML tab. The page keys and the provenance key
are the exception: fastgeoapi checks them after pygeoapi's validation and
adds them to the schema the editor serves, so the form has fields for them.

### Provider keys

| Key                            | Used by             | Meaning                                                          |
| ------------------------------ | ------------------- | ---------------------------------------------------------------- |
| `geometry_column`              | GeoParquet          | Geometry column name (default `geom`)                            |
| `bbox_column`                  | GeoParquet          | Covering column to pre-filter on; auto-detected                  |
| `store_options`                | GeoParquet, PMTiles | Store settings: `region`, `skip_signature`, `endpoint`           |
| `engine_options`               | GeoParquet          | DuckDB settings, e.g. `memory_limit`, `threads`                  |
| `options.inline_inflate_limit` | PMTiles             | Bytes above which a tile is decompressed in a worker (256 KiB)   |
| `options.leaf_cache`           | PMTiles             | Leaf directories kept in memory per process (256)                |
| `options.styles`               | PMTiles, MapLibre   | Style names mapped to MapLibre styles for the collection's pages |
| `options.default_style`        | PMTiles, MapLibre   | The style the pages open with, one of `options.styles`           |

`store_options` deserves a note: a dataset is read **where it lives**,
not where the process banks. A deployment that keeps its own data on an
S3-compatible service carries `AWS_ENDPOINT_URL_S3` for it, and without
a per-dataset endpoint every read of a dataset elsewhere would be sent
to the wrong place. An explicit `endpoint` wins over that variable, so
a public dataset on AWS next to a Tigris-hosted one is spelled
`endpoint: s3.us-west-2.amazonaws.com` with `skip_signature: true`.

See [GeoParquet provider](../how-to/geoparquet.md) for the full treatment,
including what `skip_signature` is for and why a public bucket answers a
signed request with 403.

### Page keys

The [native HTML pages](../how-to/html-pages.md) read these keys, and
pygeoapi's own pages ignore them.

| Key                | Where        | Meaning                                                                                                    |
| ------------------ | ------------ | ---------------------------------------------------------------------------------------------------------- |
| `view.center`      | a collection | Longitude and latitude, in degrees, where the collection's maps open                                       |
| `view.zoom`        | a collection | The zoom level they open at, from 0 to 24, as in WebMercatorQuad                                           |
| `server.map.style` | the server   | An `http` or `https` URL of a MapLibre style to draw the maps on, instead of the tiles of `server.map.url` |

`view` needs both keys. A page that shows data, such as the items of a
collection, fits its map to the data before it looks at `view`.

### Provenance keys

`fastgeoapi config ingest` writes an `ingest` key in every resource it
creates, and reads it on the next run to tell its own resources from the
ones written by hand. See [Ingesting a Portolan catalog](../how-to/portolan-ingest.md).

| Key                 | Where        | Meaning                                                                      |
| ------------------- | ------------ | ---------------------------------------------------------------------------- |
| `ingest.from`       | a collection | The kind of catalog the resource was ingested from: `portolan`               |
| `ingest.catalog`    | a collection | The root document of the catalog, as a URL or a path                         |
| `ingest.collection` | a collection | The id of the collection in that catalog                                     |
| `ingest.schema`     | a collection | The Portolan schema the catalog declares, an `http` or `https` URL; optional |

The first three are required, and no other key is accepted. A resource
without `ingest` counts as written by hand, so removing the key takes a
resource away from the ingest: the next run leaves it alone.

### Where the configuration itself comes from

`PYGEOAPI_CONFIG` accepts an object-storage URL as well as a path, and
the document can be reloaded without a restart. Neither is part of the
schema, because upstream reads its configuration from a local file. See
[Config from cloud storage](../how-to/cloud-config.md).
