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
write one, use the editor's YAML tab. The page keys are the exception:
fastgeoapi checks them after pygeoapi's validation and adds them to the
schema the editor serves, so the form has fields for them.

### Provider keys

| Key                            | Used by             | Meaning                                                        |
| ------------------------------ | ------------------- | -------------------------------------------------------------- |
| `geometry_column`              | GeoParquet          | Geometry column name (default `geom`)                          |
| `bbox_column`                  | GeoParquet          | Covering column to pre-filter on; auto-detected                |
| `store_options`                | GeoParquet, PMTiles | Store settings: `region`, `skip_signature`, `endpoint`         |
| `engine_options`               | GeoParquet          | DuckDB settings, e.g. `memory_limit`, `threads`                |
| `options.inline_inflate_limit` | PMTiles             | Bytes above which a tile is decompressed in a worker (256 KiB) |
| `options.leaf_cache`           | PMTiles             | Leaf directories kept in memory per process (256)              |

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

### Where the configuration itself comes from

`PYGEOAPI_CONFIG` accepts an object-storage URL as well as a path, and
the document can be reloaded without a restart. Neither is part of the
schema, because upstream reads its configuration from a local file. See
[Config from cloud storage](../how-to/cloud-config.md).
