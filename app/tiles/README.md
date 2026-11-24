# app/tiles

The contract between fastgeoapi's tile provider and the backends that read
tiles ([`contract.py`](contract.py)), and the registry that picks a backend
for a dataset ([`sources.py`](sources.py)). The provider itself is
[`app/provider/tiles.py`](../provider/tiles.py); a backend is a tile source
plus, optionally, a provider subclass naming it — PMTiles
([`app/provider/pmtiles.py`](../provider/pmtiles.py)) and martin
([`app/provider/martin.py`](../provider/martin.py)).

This file is the practical how-to for the martin backend: vector tiles cut
on request by [martin](https://martin.maplibre.org/), in-process, through
the `martin-py` bindings. See `app/provider/martin.py`'s docstring for the
design.

## 1. Serve a collection's tiles with martin

### Install the optional dependency

`martin-py` is the `martin` extra. It ships as GitHub Release wheels, not
(yet) published on PyPI — see `[tool.uv.sources]` in `pyproject.toml`.

```shell
uv sync --extra martin
```

Without it, a collection configured with the martin provider fails to load
with an error saying to install the extra.

### Configure a tile provider in the pygeoapi config

Add a `tile` provider to a resource. martin tiles GeoParquet (a file, a
glob or a bucket prefix), GeoJSON and PMTiles:

```yaml
lakes:
  type: collection
  # ... title, extents, other providers ...
  providers:
    - type: tile
      name: app.provider.martin.MartinTilesProvider
      data: tests/data/ne_110m_lakes.geojson
      options:
        zoom: { min: 0, max: 14 }
        schemes: [WebMercatorQuad]
      format:
        name: pbf
        mimetype: application/vnd.mapbox-vector-tile
```

For GeoParquet, `options` also take `geometry_column` (default `geom`) and
`srid` (default `4326`); `store_options` reach a private bucket the same
way they do for the GeoParquet feature provider. `layer_id` names the layer
in the tiles (default: the file's stem), `worker_threads` and
`cache_size_mb` size martin's runtime and tile cache.

### Request a tile

The tiles go out through the OGC API Tiles routes, behind the same auth as
every other collection:

```shell
curl 'http://localhost:5000/geoapi/collections/lakes/tiles/WebMercatorQuad/0/0/0?f=mvt'
curl 'http://localhost:5000/geoapi/collections/lakes/tiles/WebMercatorQuad/metadata?f=tilejson'
```

Note the order: `{tileMatrix}/{tileRow}/{tileCol}`, so `z/y/x`.

- `200` with the tile; `204` where the data has nothing.
- `404`: outside the configured `zoom` or the tile matrix.
- `500`: martin could not load the data or cut the tile; the details are in
  fastgeoapi's log, not in the response.

## 2. Load it as a vector tile source in QGIS

The response is `application/vnd.mapbox-vector-tile` — Mapbox Vector Tiles,
**not** raster PNG/JPEG. QGIS handles that through its **Vector Tiles**
connection type, not the plain **XYZ Tiles** one.

**Layer ▸ Add Layer ▸ Add Vector Tile Layer... ▸ New ▸ New Generic
Connection**, then set:

- **Name**: anything, e.g. `fastgeoapi lakes`
- **URL**:

  ```text
  http://localhost:5000/geoapi/collections/lakes/tiles/WebMercatorQuad/{z}/{y}/{x}?f=mvt
  ```

  `{z}`, `{y}`, `{x}` lowercase, in that order.

- **Min./max. zoom level**: those of the provider's `zoom` option.
- **Authentication**: none, unless the API key or OAuth2 is enabled.

Click **OK**, select the new connection, **Add**.

### Troubleshooting

| Symptom in QGIS                            | Likely cause                                                                                   |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| Layer added but nothing draws              | Wrong collection id, `{y}`/`{x}` swapped, or the data has no features nearby                   |
| Connection fails outright                  | Server not running, port/host wrong, or the collection failed to load — check fastgeoapi's log |
| Tiles look like garbage / layer won't load | Added as an **XYZ Tiles** connection instead of **Vector Tiles**                               |
