---
icon: material/map
---

# :material-map: MapLibre provider

An OGC API - Maps provider that draws PNG maps of a PMTiles archive, of
vector or raster tiles, with MapLibre Native, the engine behind MapLibre GL. The renderer runs in its
own process and reads the archive in place, from a local path or a
bucket, the way the [PMTiles provider](pmtiles.md) does. The map route
awaits the provider, so a map being drawn keeps no worker thread busy.

## Install

The renderer ships as Linux wheels of the mlnative fork, for x86_64 and
aarch64. They need glibc 2.39 or later, as on Ubuntu 24.04. From a
checkout, install the `maps` dependency group with the `pmtiles` extra,
which the provider needs to read the archive:

```bash
uv sync --group maps --extra pmtiles
```

`uv sync` removes the packages the command does not name, so add every
other extra the server uses, such as `--extra geoparquet`.

Dependency groups are not published to PyPI. An installation from PyPI
needs the `pmtiles` extra, Pillow and the mlnative wheel for the machine,
from the [fork's release](https://github.com/francbartoli/mlnative/releases/tag/v0.4.0.dev1)
(`x86_64` or `aarch64` in the file name):

```bash
pip install "fastgeoapi[pmtiles]" "pillow>=11" \
  https://github.com/francbartoli/mlnative/releases/download/v0.4.0.dev1/mlnative-0.4.0.dev1-py3-none-manylinux_2_39_x86_64.whl
```

The system needs the libraries the MapLibre Native binary links, and
Vulkan with lavapipe to draw without a GPU:

```bash
apt-get install libuv1 libvulkan1 mesa-vulkan-drivers libicu74 libcurl4t64 \
  libpng16-16t64 libjpeg-turbo8 libwebp7
```

Without the group, a map answers 500 with "map rendering is not available"
and says what to install; without the `pmtiles` extra, it answers 500 with
"map source not available" and names the extra. The rest of the server
needs neither.

## Configuration

Add a provider of type `map` to a collection, next to its tiles if it has
them:

```yaml
providers:
  - type: map
    name: app.provider.maplibre.MapLibreMapProvider
    data: s3://my-bucket/tiles/roads.pmtiles
    storage_crs: http://www.opengis.net/def/crs/EPSG/0/3857
    store_options:
      endpoint: fly.storage.tigris.dev
      region: auto
    options:
      styles:
        night: s3://my-bucket/styles/night.json
      default_style: night
    format:
      name: png
      mimetype: image/png
```

`storage_crs` must be EPSG:3857: maps are drawn in Web Mercator only.

| Option          | Default                                  | Meaning                                                                                                                                             |
| --------------- | ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `max_size`      | 2048                                     | The largest `width` or `height`; larger answers 413, and below 1 answers 400.                                                                       |
| `queue`         | 8                                        | Maps that may wait for the renderer; one more answers 503.                                                                                          |
| `timeout`       | 30                                       | Seconds a map may take, the wait for the renderer included; longer answers 504.                                                                     |
| `render_limit`  | four times `timeout`                     | Seconds a render goes on after its map answered 504, so the tiles it reads stay cached; past it the renderer is replaced.                           |
| `max_rss_mb`    | 600                                      | Memory of the renderer process after a map; above it the process is replaced.                                                                       |
| `styles`        | none                                     | Style names mapped to MapLibre style files, local or in a bucket.                                                                                   |
| `default_style` | none                                     | The style drawn when a request names none, one of `styles`; without it, a plain style of the archive's vector layers or raster tiles.               |
| `style_source`  | `archive`                                | The name the styles give the collection's source in their `sources`.                                                                                |
| `data_url`      | none                                     | The https address of the data in a public bucket; needed only when the range cache is off and the bucket is read with `skip_signature`.             |
| `sign_ttl`      | 3600                                     | Seconds a presigned data URL lasts; it is renewed when a fifth is left.                                                                             |
| `range_cache`   | true                                     | Read a remote archive through the range cache; `false` gives the renderer the public or signed URL instead.                                         |
| `renderer`      | `app.maps.mlnative.create_renderer`      | The function that builds the renderer from these options; another engine plugs in here.                                                             |
| `tile_size`     | the first tile's width                   | The width in pixels of the tiles of a raster archive.                                                                                               |
| `dem`           | none                                     | `terrarium` or `mapbox` for a raster archive of elevations: without a configured style, the relief is drawn as a hillshade.                         |
| `style_factory` | `app.maps.styles.create_maplibre_styles` | The function that builds the styles from the source, the style documents and these options; it must give styles in the language the renderer reads. |

Each style is read at its first map. A style file that cannot be read
answers 500 "style ... could not be read" for that style only; the other
styles keep drawing.

The renderer reads a remote archive through this process: a server on
127.0.0.1, on a port the system picks and with a random token in every
path, hands it the byte ranges from the range cache described in the
PMTiles guide. The renderer never sees a signed URL, and a renderer
process started again finds the ranges an earlier one read. A map still
being drawn when a configuration reload replaces the provider keeps
reading its ranges to the end. With the range cache off, a private
bucket still works without `data_url`: the server signs a URL with the
store's credentials and gives only that URL to the renderer.

The first map reads the archive header to tell vector tiles from raster
ones. A raster archive of PNG, JPEG or WebP tiles is drawn as a raster
layer; an archive of AVIF tiles answers 500 with "map source not
drawable", because MapLibre Native cannot decode AVIF. A style that declares the
archive's source with its `type` keeps that source and its settings, and
the header is not read for it, so a `raster-dem` source declared without
`encoding` is read as `mapbox` by MapLibre. With `dem`, the default style
shades the relief.

## What a request can ask

A request can pass `bbox`, `bbox-crs`, `crs`, `width`, `height`,
`transparent` and `f`, as in OGC API - Maps. `crs`, when given, must be the
EPSG:3857 URI: any other CRS answers 400. `f` takes `png`, and `f=html`
returns the same PNG, as pygeoapi's map route does, since there is no HTML
map page.

The bbox is read in CRS84 unless `bbox-crs` names another CRS. Two values
answer 500, because of how pygeoapi reads the parameter: the CRS84 URI
itself, so leave `bbox-crs` out for CRS84, and a bare EPSG code such as
`4326`, so give the EPSG URI instead.

A bbox with another aspect than the image is stretched to it, as a WMS
GetMap does. `datetime`, `subset` and `properties` are ignored.

## Limits to know

One renderer process serves each map provider and draws one map at a
time. Under load, maps wait in a queue of `queue` places; past it they
get a 503 with "the map renderer is busy, retry later" and
`Retry-After: 5`. A map whose client disconnects leaves the queue at once,
so a browser map that pans or zooms before its image arrives does not
fill it. A map that answers 504 is still drawn in the background, up to
`render_limit`, so asking for it again a little later is often quick; a
render that has started goes on even after its client has left, for the
same reason.
The first map of a new area waits for the tiles it needs to be read from
the bucket. A small view took from 2 to 9 seconds in our measurements,
depending on how far the bucket is. A wide view over a large archive needs
many more tiles: the whole world from the Overture divisions archive, read
from Europe, took more than 90 seconds cold and answered 504 while the
render went on in the background.

When the archive changes, a map already being drawn may fail with a 500:
it asks for ranges of the old version, the ones not cached any more
answer 404, and the renderer gives the map up. The next map reads the new
version.

The collection page asks for an image as wide as its map, so `max_size`
should stay above the widest map a browser will show: a wider map gets a
413 and keeps its previous image.

A style with labels needs a `glyphs` URL the renderer can reach. The MCP
server gives each map collection a tool that returns the image to the
model.
