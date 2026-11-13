# app/tiles

In-process tile-serving surfaces that sit alongside pygeoapi's own OGC API
tile provider. Today that's one module: [`martin_wrapper.py`](martin_wrapper.py),
which mounts `/geoapi/martin-wrapper/{source_ids}/{z}/{x}/{y}` — vector tiles served
straight from [martin-py](https://martin.maplibre.org/)'s in-process
bindings, for benchmarking pygeoapi's tile path against martin's own under
the same process and load generator. See that module's docstring for the
full design rationale (ADR-0003); this file is the practical how-to.

**Opt-in, off by default, and unauthenticated.** This surface carries none
of the auth middleware the rest of the API gets — never enable it on a
public deployment.

## 1. Run fastgeoapi with `/martin-wrapper` enabled

### Install the optional dependency

`martin-py` is the `martin_wrapper` extra. It ships as a locally-built
wheel, not (yet) published on PyPI — see `[tool.uv.sources]` in
`pyproject.toml`.

```shell
uv sync --extra martin_wrapper
```

If this extra isn't installed, setting the config below still starts the
server — it just logs a warning and skips the mount rather than crashing.

### Point `FASTGEOAPI_MARTIN_WRAPPER_CONFIG` at some data

In dev (`ENV_STATE=dev`, the default locally), settings are read with a
`DEV_` prefix — add one of these to your `.env`:

**`auto`** — derives the Martin config from the pygeoapi config this same
boot already loaded (`app.tiles.martin_wrapper._martin_config_from_pygeoapi`),
no second file to keep in sync:

```shell
DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG=auto
```

Only providers this build of martin-py can actually open are translated —
keyed by the pygeoapi resource id:

| pygeoapi provider                                                                    | martin-py source            |
| ------------------------------------------------------------------------------------ | --------------------------- |
| `GeoJSON`, or `data` ending `.geojson`/`.json`                                       | `geojson`                   |
| `app.provider.geoparquet.GeoParquetProvider`, `Parquet`, or `data` ending `.parquet` | `duckdb` (reads GeoParquet) |
| `data` ending `.pmtiles`                                                             | `pmtiles`                   |

Everything else (CSV, OGR/GPKG, PostgreSQL, MVT-\*, rasterio, xarray, ...)
has no equivalent here and is skipped.

**A path to a hand-written Martin config file** — the same format the
`martin` server itself reads:

```shell
DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG=/path/to/martin-config.yaml
```

```yaml
# martin-config.yaml
geojson:
  sources:
    lakes: tests/data/ne_110m_lakes.geojson
```

### Start the server

```shell
uv run fastgeoapi run --host 0.0.0.0 --port 5000 --reload
```

A successful mount logs:

```
Martin wrapper endpoint mounted at /geoapi/martin-wrapper (config: ...); this surface is UNAUTHENTICATED and for benchmarking only.
```

### Try it

```shell
curl http://localhost:5000/geoapi/martin-wrapper/<source_id>/<z>/<x>/<y>
# e.g. curl http://localhost:5000/geoapi/martin-wrapper/lakes/0/0/0
```

`<source_id>` is the pygeoapi resource id (`auto` mode) or the source
key/`layer_id` from your config file. A `404` with `{"code": "NotFound", ...}`
means either the source id is wrong or that tile genuinely has no data.

## 2. Load it as a vector tile source in QGIS

The response is `application/x-protobuf` — Mapbox Vector Tiles, **not**
raster PNG/JPEG. QGIS handles that through its **Vector Tiles** connection
type, not the plain **XYZ Tiles** one (which expects raster imagery and
will fail to render this).

**Layer ▸ Add Layer ▸ Add Vector Tile Layer... ▸ New ▸ New Generic
Connection**, then set:

- **Name**: anything, e.g. `fastgeoapi martin-wrapper`
- **URL**:
  ```
  http://localhost:5000/geoapi/martin-wrapper/<source_id>/{z}/{x}/{y}
  ```
  `{z}`, `{x}`, `{y}` lowercase, exactly as shown — QGIS's placeholder
  syntax matches the wrapper's own route
  (`/{source_ids}/{z:int}/{x:int}/{y:int}`).
- **Min./max. zoom level**: leave the defaults (0–14) unless your data
  needs narrower bounds.
- **Authentication**: none — leave blank.

Click **OK**, select the new connection, **Add**. The layer should render
with QGIS's default vector-tile styling (edit it via the layer's
**Symbology** tab, or load/generate a style resource separately — this
endpoint serves tiles only, no accompanying style document).

### Troubleshooting

| Symptom in QGIS                            | Likely cause                                                                                                                                                  |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Layer added but nothing draws              | Wrong `<source_id>`, or the resource's data genuinely has no features nearby                                                                                  |
| Connection fails outright                  | Server not running, port/host wrong, or `/martin-wrapper` wasn't mounted — check the startup log for the warning about the missing dependency or unset config |
| Tiles look like garbage / layer won't load | Added as an **XYZ Tiles** connection instead of **Vector Tiles** — protobuf isn't raster imagery                                                              |
