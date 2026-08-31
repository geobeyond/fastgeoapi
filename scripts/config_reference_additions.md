## fastgeoapi additions

The keys below are **not in pygeoapi's schema**. They are read by
fastgeoapi's own providers, and they pass validation because the schema
declares no `additionalProperties` — which also means nothing upstream
documents them. This section is hand-written and is never touched by the
generator.

Being outside the schema has one practical consequence: the
[configuration editor](../how-to/configuration-editor.md)'s form cannot create
them, because no widget can be generated for a key the schema does not
mention. It preserves them faithfully once they exist; to write one, use
the editor's YAML tab.

### Provider keys

| Key               | Used by    | Meaning                                                |
| ----------------- | ---------- | ------------------------------------------------------ |
| `geometry_column` | GeoParquet | Geometry column name (default `geom`)                  |
| `bbox_column`     | GeoParquet | Covering column to pre-filter on; auto-detected        |
| `store_options`   | GeoParquet | Store settings: `region`, `skip_signature`, `endpoint` |
| `engine_options`  | GeoParquet | DuckDB settings, e.g. `memory_limit`, `threads`        |

`store_options` deserves a note: a dataset is read **where it lives**,
not where the process banks. A deployment that keeps its own data on an
S3-compatible service carries `AWS_ENDPOINT_URL_S3` for it, and without
a per-dataset endpoint every read of a dataset elsewhere would be sent
to the wrong place.

See [GeoParquet provider](../how-to/geoparquet.md) for the full treatment,
including what `skip_signature` is for and why a public bucket answers a
signed request with 403.

### Where the configuration itself comes from

`PYGEOAPI_CONFIG` accepts an object-storage URL as well as a path, and
the document can be reloaded without a restart. Neither is part of the
schema, because upstream reads its configuration from a local file. See
[Config from cloud storage](../how-to/cloud-config.md).
