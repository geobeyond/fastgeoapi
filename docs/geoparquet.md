# GeoParquet provider

A read-only OGC API Features provider that serves GeoParquet from a
local path or an object-storage bucket, with CQL2 filters — spatial
predicates included — evaluated inside [DuckDB](https://duckdb.org/).

Install the extra:

```bash
pip install 'fastgeoapi[geoparquet]'
```

## Configuration

Declare it by dotted path in the pygeoapi configuration:

```yaml
resources:
  lakes:
    type: collection
    title:
      en: Lakes
    description:
      en: Lakes served from GeoParquet
    keywords:
      en: [lakes]
    extents:
      spatial:
        bbox: [-180, -90, 180, 90]
        crs: http://www.opengis.net/def/crs/OGC/1.3/CRS84
    providers:
      - type: feature
        name: app.provider.geoparquet.GeoParquetProvider
        data: s3://my-bucket/tenants/acme/lakes
        id_field: id
        geometry_column: geom
        time_field: observed_at
```

| Key               | Required | Meaning                                                |
| ----------------- | -------- | ------------------------------------------------------ |
| `data`            | yes      | Dataset source: a file, a glob, or a directory root    |
| `id_field`        | yes      | Column carrying the feature identifier                 |
| `geometry_column` | no       | Geometry column name (default `geom`)                  |
| `time_field`      | no       | Column the `datetime` parameter filters on             |
| `properties`      | no       | Restrict which columns are returned by default         |
| `bbox_column`     | no       | Covering column to pre-filter on (auto-detected)       |
| `count`           | no       | `false` drops `numberMatched` from item responses      |
| `store_options`   | no       | Store settings: `region`, `skip_signature`, `endpoint` |

### Source shapes

| Shape                 | Example                                               |
| --------------------- | ----------------------------------------------------- |
| Single file           | `s3://bucket/lakes.parquet`                           |
| Glob                  | `s3://bucket/lakes/*.parquet`                         |
| Hive-partitioned root | `s3://bucket/lakes` → scanned as `lakes/**/*.parquet` |

A directory root is read with hive partitioning enabled, so a query
that filters on a partition column reads only the matching partitions.

### Sources and credentials

`data` accepts the same sources as the configuration itself — local
paths, `s3://`, `gs://`, `az://`, and any S3-compatible endpoint — and
credentials come exclusively from each provider's standard environment
variables. See [Config from cloud object storage](cloud-config.md); the
same rules apply here.

Cloud reads go through obstore's fsspec filesystem, registered in
DuckDB, so credentials are resolved in exactly one place. Local paths
are read by DuckDB directly.

Per-dataset store settings travel in `store_options`. A public dataset
must be read anonymously and name its region, otherwise obstore signs
the request, goes looking for credentials, and fails after roughly
twenty seconds of EC2-metadata retries:

```yaml
data: s3://overturemaps-us-west-2/release/2026-08-19.0/theme=divisions/type=division/
store_options:
  region: us-west-2
  skip_signature: true
```

The same key carries `endpoint` for an S3-compatible service.

## Query capabilities

| Capability            | Notes                                                          |
| --------------------- | -------------------------------------------------------------- |
| `limit` / `offset`    | Pushed down as `LIMIT`/`OFFSET`                                |
| `bbox`                | `ST_Intersects` against the request envelope, in-engine        |
| `datetime`            | Instants and intervals, `..` for open ends; needs `time_field` |
| Property equality     | e.g. `?country=it`                                             |
| `properties` (select) | Column projection                                              |
| `skipGeometry`        | Skips the geometry entirely                                    |
| `sortby`              | Ascending and descending                                       |
| `resulttype=hits`     | `COUNT` only, no features materialised                         |
| `filter` (CQL2)       | `cql2-text` and `cql2-json`                                    |

CQL2 support covers comparisons, `AND`/`OR`/`NOT`, `LIKE`, `IN`,
`BETWEEN`, `IS NULL`, arithmetic, the spatial predicates
(`S_INTERSECTS`, `S_WITHIN`, `S_CONTAINS`, `S_DISJOINT`, `S_TOUCHES`,
`S_CROSSES`, `S_OVERLAPS`, `S_EQUALS`) and the instant temporal
operators (`T_AFTER`, `T_BEFORE`, `T_EQUALS`). Interval temporal
operators are refused with a clear error rather than approximated,
since honouring them would need a second time column.

Example:

```bash
curl "https://example.org/geoapi/collections/lakes/items?\
filter-lang=cql2-text&\
filter=S_INTERSECTS(geom, POLYGON((11 41, 14 41, 14 43, 11 43, 11 41))) AND depth > 10"
```

## Performance: the file and the reader both decide

Measured against the public Overture Maps release (`theme=divisions`,
one 578 MB file in `us-west-2`, read from Europe):

| | Same file, remote | Same file, local disk | 7 MB regional extract |
| --- | --- | --- | --- |
| First page | ~15–20 s | 31 ms | 5 ms |
| Warm page | ~15 s | 30 ms | 3 ms |
| `bbox` window | ~20 s | 36 ms | 5 ms |

Two separate effects hide in those columns. **Locality is worth roughly
500×** (the middle column is the very same file, only nearer), while
**dataset size is worth about 10×**. Shrinking the data is the smaller
lever; moving it is the larger one.

### Give the file the shape the format expects

Row-group pruning only works when the file carries usable statistics.
Following the GeoParquet spec's own distribution guidance:

- **zstd** compression, level 15 or above;
- **spatially sorted** (Hilbert) before writing — without it, every
  row group's bounding box spans most of the dataset and nothing can be
  skipped;
- **row groups of 50k–150k rows**;
- a **covering `bbox` column** (GeoParquet 1.1) or native geometry types
  (2.0); the provider detects the covering automatically, or takes
  `bbox_column`;
- **partition** beyond a couple of gigabytes.

`geoparquet-io` applies these as defaults, and a plain DuckDB
`COPY … TO … (FORMAT parquet, ROW_GROUP_SIZE 100000)` gets you most of
the way.

### Keep the data near the server, and read it with a caching reader

Cross-region latency is a floor no predicate can lower: reading the
Overture file from Europe cost seconds per request no matter how well
the file was laid out — its row groups are in fact reasonably sorted
(each covers about 5% of world longitude, and a window over Rome touches
16 of 256).

Repeated reads are the other half of the story. DuckDB caches the blocks
it has already fetched, but only on its own I/O path: the same query
through the obstore fsspec bridge stayed at ~12 s on every repetition,
while DuckDB's native `httpfs` answered the second and third in
milliseconds. This mirrors what GDAL sees on the desktop side
([GDAL #8225](https://github.com/OSGeo/gdal/issues/8225): 542 MB
downloaded for a 507 MB file), and it is why "cloud-native" can end up
costing more than a plain download when the reader cannot cache.

Practical order of effect: put the data in the same region as the
server, shape it as above, and only then reach for materialising a local
copy.

### Cheap wins on the request itself

- `count: false` drops `numberMatched` from item responses (a
  `resulttype=hits` request still answers) — worth seconds per request
  on a remote dataset.
- Ask for the columns you need with `properties=` — Parquet is
  columnar, so unrequested columns are never read.

## Preparing datasets

Any GeoParquet writer works. For partitioning, spatial sorting and
bbox covering columns, [geoparquet-io](https://pypi.org/project/geoparquet-io/)
is a convenient offline tool — it is not needed at runtime.

DuckDB can also produce a partitioned dataset directly:

```sql
COPY (SELECT * FROM 'lakes.parquet')
TO 'lakes' (FORMAT parquet, PARTITION_BY (country));
```

## Limitations

- **Read-only:** no create, update or delete.
- The `spatial` extension is vendored in the container image. Outside
  it, the first connection installs the extension, which needs network
  access once.
- Geometries are served in the dataset's own CRS; declare it with
  `storage_crs` when it is not CRS84.
