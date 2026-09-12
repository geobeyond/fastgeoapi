---
icon: material/grid
---

# :material-grid: PMTiles provider

An OGC API - Tiles provider that serves Mapbox Vector Tiles straight
from a [PMTiles](https://github.com/protomaps/PMTiles) archive on a
local path or an object-storage bucket. The archive is read by byte
range and never copied, so a collection can sit on Overture Maps'
18 GB `places.pmtiles` as easily as on a 100 MB regional extract. The
provider is natively asynchronous: the tile route awaits it, and one
process keeps many tiles in flight instead of one per thread.

Install the extra:

```bash
pip install 'fastgeoapi[pmtiles]'
```

## Configuration

Declare it by dotted path in the pygeoapi configuration:

```yaml
resources:
  overture-places-tiles:
    type: collection
    title: Overture places as vector tiles
    description: The Overture Maps places release, read in place
    keywords: [overture, places, pmtiles]
    extents:
      spatial:
        bbox: [-180, -85.0511287, 180, 85.0511287]
        crs: http://www.opengis.net/def/crs/OGC/1.3/CRS84
    providers:
      - type: tile
        name: app.provider.pmtiles.PMTilesProvider
        data: s3://overturemaps-extras-us-west-2/tiles/2026-08-19.0/places.pmtiles
        store_options:
          region: us-west-2
          skip_signature: true
        options:
          zoom:
            min: 14
            max: 14
          schemes: [WebMercatorQuad]
        format:
          name: pbf
          mimetype: application/vnd.mapbox-vector-tile
```

| Key                            | Required | Meaning                                                             |
| ------------------------------ | -------- | ------------------------------------------------------------------- |
| `data`                         | yes      | The archive: a local path or an object URL                          |
| `options.zoom`                 | yes      | `min`/`max` the collection advertises; intersected with the archive |
| `options.schemes`              | yes      | `[WebMercatorQuad]` — the only tiling scheme PMTiles archives use   |
| `format`                       | yes      | `name: pbf` (or `mvt`) with the vector-tile media type              |
| `store_options`                | no       | Store settings: `region`, `skip_signature`, `endpoint`              |
| `options.inline_inflate_limit` | no       | Bytes above which a tile is decompressed in a worker (256 KiB)      |
| `options.leaf_cache`           | no       | Leaf directories kept in memory per process (256)                   |

The archive itself carries zoom limits, in the `vector_layers` of its
metadata. The collection serves the intersection: a request outside it
is `404 Not Found`, a request inside it for a tile the archive does not
hold is `204 No Content`. Overture's `places` archive says `0–14` in
its header but only holds level 14, which is why the example pins
`zoom` to `14`; trust the metadata over the header.

Directories must be gzip-compressed, which is what every writer
produces. Tiles may be gzip-compressed or stored as they are; an
archive with another tile compression is refused with a clear error
rather than served wrong.

### Where the archive lives

`data` accepts the same sources as the configuration document: local
paths, `s3://`, `gs://`, `az://`, and any S3-compatible service through
`endpoint`. Credentials come exclusively from each provider's standard
environment variables — see
[Config from cloud object storage](cloud-config.md).

A public bucket must say so and name its region, exactly as for the
[GeoParquet provider](geoparquet.md#sources-and-credentials): without
`skip_signature` the request is signed with whatever credentials the
process carries, and a public bucket answers a signed request with
`403 Forbidden`.

**An explicit `endpoint` wins over the environment.** A deployment that
keeps its own data on an S3-compatible service carries
`AWS_ENDPOINT_URL_S3` for it. The object-store layer would otherwise
send every read there, including the reads of an archive that lives on
AWS. Name the archive's own endpoint and the reads go where the data
is:

```yaml
store_options:
  endpoint: s3.us-west-2.amazonaws.com
  region: us-west-2
  skip_signature: true
```

The public demo runs exactly this shape: its own archive on Tigris in
the deployment's region, Overture's archive on AWS, in one process.

## What is served

| Path                                                          | Content                                                    |
| ------------------------------------------------------------- | ---------------------------------------------------------- |
| `/collections/{id}/tiles`                                     | The tilesets: one, `WebMercatorQuad`                       |
| `/collections/{id}/tiles/WebMercatorQuad`                     | Tileset metadata with the tile URL template                |
| `/collections/{id}/tiles/WebMercatorQuad/metadata?f=tilejson` | TileJSON built from the archive: name, attribution, layers |
| `/collections/{id}/tiles/WebMercatorQuad/{z}/{y}/{x}?f=pbf`   | The tile, decompressed; `f=mvt` is accepted too            |

Two things about the tile URL are worth reading twice. The path order
is pygeoapi's, **`{tileMatrix}/{tileRow}/{tileCol}`, that is `z/y/x`**,
not the `z/x/y` most tile servers use. And the `f` parameter is
required: without it pygeoapi answers `400 Bad Request`.

Tiles leave the provider decompressed and pygeoapi gzips them on the
wire when the client accepts it, so a client sees ordinary
`Content-Encoding: gzip` and never a double-compressed body.

| Response | Meaning                                                           |
| -------- | ----------------------------------------------------------------- |
| `200`    | The tile                                                          |
| `204`    | Inside the limits, but the archive holds nothing there            |
| `404`    | Outside the zoom or matrix limits, or a template pasted literally |
| `400`    | No `f` parameter                                                  |

The Tiles conformance classes appear in `/conformance` only when a tile
collection is configured, like every other specification fastgeoapi
mounts. With the MCP server enabled, the tilesets and the TileJSON
become tools — an assistant can discover the template — while the
binary tile operation is deliberately excluded: a 5 MB tile is not a
tool result.

## Using the tiles

**QGIS**: add a Vector Tiles connection with the URL

```text
https://example.org/geoapi/collections/lazio-roads-tiles/tiles/WebMercatorQuad/{z}/{y}/{x}?f=pbf
```

with the `{z}/{y}/{x}` order above, and the collection's zoom range as
min and max. On a protected deployment attach an authentication
configuration that sends the bearer token.

**MapLibre GL**:

```js
map.addSource("roads", {
  type: "vector",
  tiles: [
    "https://example.org/geoapi/collections/lazio-roads-tiles/tiles/WebMercatorQuad/{z}/{y}/{x}?f=pbf",
  ],
  minzoom: 0,
  maxzoom: 13,
});
map.addLayer({
  id: "roads",
  type: "line",
  source: "roads",
  "source-layer": "roads",
});
```

`source-layer` is the layer id from the TileJSON's `vector_layers`.
On a protected deployment set `transformRequest` to add the
`Authorization` header.

**The built-in HTML page** (`/collections/{id}/tiles?f=html`) fits its
map to the collection's `extents.bbox` and asks for tiles at every zoom
from there. With an archive that only holds one level — Overture's
`places` at 14 — the map stays empty until you zoom that far, with no
message. Zoom in, or give the collection a bbox tight enough for the
viewer to open at a level the archive holds.

## Performance: what a tile costs

Opening an archive costs three ranged reads — header, root directory,
metadata — once per process; the provider is `THREAD_SAFE`, so pygeoapi
keeps one instance and the caches pay off. After that a tile costs one
read of the leaf directory it sits in, kept in an LRU cache, and one
read of the tile itself. Overture's archives point every root entry at
a leaf, so a tile in a part of the world the process has not visited
costs two reads, and the next tile nearby costs one. A cold burst of
identical requests shares its reads: fifty tiles asked at once do not
open the archive fifty times.

Measured on the public demo (1 vCPU / 1 GB in Paris, client in Rome,
blocks of 20 tiles per city, first pass with a cold leaf):

| Archive                               | Placement    | One tile at a time | First tile of a cold city | 8 in flight, 20 tiles |
| ------------------------------------- | ------------ | ------------------ | ------------------------- | --------------------- |
| Overture `places`, z14 (18 GB)        | cross-region | 0.35–0.40 s        | 2.2–2.7 s                 | 1.7–2.6 s             |
| Lazio roads, z13 (100 MB, tippecanoe) | same region  | 0.26–0.28 s        | 0.5 s                     | 1.4–1.6 s             |

The client's own round trip to Paris is about 0.2 s of every figure,
so the in-region advantage shows most where it matters: the first tile
of a region nobody has asked for yet, where the leaf read is a short
hop instead of a transatlantic one. Eight requests in flight bring 20
tiles from 8–11 s to under three on a single vCPU because the route is
asynchronous: the process waits on the network for all of them at
once, where a thread-per-request chain would serve five and queue the
rest.

The lesson is the GeoParquet one again: keep the archive near the
server. Bytes are the other lever — an Overture `places` tile over Rome
is 1 MB compressed and 4.7 MB decompressed, and a Lazio z6 tile
straight out of `tippecanoe -zg` is 770 KB — and it is decided when the
archive is built, not at request time. Tiles above
`inline_inflate_limit` are decompressed in a worker so a large one does
not stall the loop; there is no tile cache in the process, so heavy
public traffic belongs behind a CDN.

## Preparing an archive

Any PMTiles writer works: [tippecanoe](https://github.com/felt/tippecanoe)
(`-o archive.pmtiles`), [Planetiler](https://github.com/onthegomap/planetiler),
or `pmtiles convert` from an MBTiles file. The Lazio archive on the demo
came out of the GeoParquet staging described in
[Staging an Overture extract](geoparquet.md#staging-an-overture-extract),
in two offline steps:

```bash
# 1. A slim GeoJSONSeq from the extract, with DuckDB's spatial extension
duckdb -c "
LOAD spatial;
COPY (SELECT id, subtype, class, subclass, name, geometry
      FROM read_parquet('transportation-lazio.parquet'))
TO 'lazio-roads.geojsonl' WITH (FORMAT GDAL, DRIVER 'GeoJSONSeq');"

# 2. The archive; -zg picks the maximum zoom from the data
tippecanoe -o lazio-roads.pmtiles -l roads \
    -n "Lazio roads (Overture segments)" -A "© Overture Maps Foundation, ODbL" \
    -zg --drop-densest-as-needed --extend-zooms-if-still-dropping \
    --coalesce-densest-as-needed lazio-roads.geojsonl
```

743k segments became a 100 MB archive with 9,741 tiles at zoom 0–13
in about three minutes. Keep the attributes to what the map needs:
every property travels inside every tile that shows the feature.

Upload it like any object — for a large file prefer a multipart upload
from a file handle — and point `data` at it. The archive is opened on
the first request, never at startup, so a slow bucket does not slow the
boot.

Overture Maps publishes ready-made archives per theme at
`s3://overturemaps-extras-us-west-2/tiles/<release>/<theme>.pmtiles`
(public, `us-west-2`): `places`, `divisions`, `base`, `buildings`,
`transportation`, `addresses`. They are large — 18 to 198 GB — and
read in place, which is the point.

## Limitations

- **WebMercatorQuad only**, which is what PMTiles archives contain.
- **Vector tiles only**: a raster PMTiles archive is refused.
- **Read-only**, one archive per collection.
- Directories must be gzip-compressed (every writer's default).
- No tile cache in the process: put a CDN in front for public traffic.
