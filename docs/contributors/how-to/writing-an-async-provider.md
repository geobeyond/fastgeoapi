---
icon: material/lightning-bolt-outline
---

# :material-lightning-bolt-outline: Writing an async provider

A fastgeoapi provider is a pygeoapi provider with one thing added: it
can be awaited. pygeoapi's own contract stays synchronous and untouched;
the asynchronous face sits beside it, and the tile route uses it when a
provider says it can. This page shows how to write both kinds, with two
worked examples: a format read piecewise through a parser of our own,
and a real Cloud Optimized GeoTIFF served through
[async-tiff](https://pypi.org/project/async-tiff/), a library that is
asynchronous itself. Why it is shaped this way is in
[Two faces for a provider](../explanation/async-providers.md).

## The shape of a provider

```python
from pygeoapi.provider.base_mvt import BaseMVTProvider

from app.provider.base import AsyncProviderMixin, StorageBackedMixin


class ArchiveTiles(AsyncProviderMixin, StorageBackedMixin, BaseMVTProvider):
    THREAD_SAFE = True
    native_async = True
```

Three things are fixed by that first line.

**The mixin goes first.** pygeoapi's root classes (`BaseProvider`,
`BaseTileProvider`, `BaseMVTProvider`) never call `super().__init__()`.
Placed after them, `AsyncProviderMixin.__init__` would never run, the
provider definition would not be captured, and `StorageBackedMixin`
would fail with a message naming exactly this line.

**The root is pygeoapi's.** The API layer reads attributes off the
instance (`options`, `format_type`, `fields`), calls `get_layer()`
inline, and builds the class with a single `provider_def` argument. A
Protocol alone would not satisfy it; the root class is the price of
compatibility, and composition does the rest.

**`native_async` is a declaration.** `True` means "my async methods
await their I/O for real". Nothing inspects your code to find out; a
wrapper around a blocking call would pass such an inspection and be a
lie. Leave the default `False` and the provider is still awaitable,
through a thread, which is the honest answer for a CPU-bound engine.

`THREAD_SAFE = True` opts into the process-wide instance cache: pygeoapi
loads the provider on every request, and without the opt-in every
request gets a fresh instance and any header or index you cached is
gone. The instance is then shared between the threadpool and the event
loop, so anything it mutates after construction needs a lock.

## Step 1: write the parser without I/O

A format read by ranges only needs "these bytes at this offset". Write
that as a generator: it _yields_ `(offset, length)`, _receives_ the
bytes, and _returns_ its result. It never opens anything, so it is
tested once, in memory, and both faces of the provider fall out of it.

The example is a toy archive: a 4-byte big-endian count, then that many
20-byte index records of `z, x, y, offset, length` as 32-bit integers,
then the tile data.

```python
import struct

from app.provider.sansio import Core

RECORD = struct.Struct(">IIIII")


def read_index() -> Core[dict[tuple[int, int, int], tuple[int, int]]]:
    """Every tile's `(offset, length)`, keyed by `(z, x, y)`."""
    (count,) = struct.unpack(">I", (yield (0, 4)))
    raw = yield (4, count * RECORD.size)
    index = {}
    for z, x, y, offset, length in RECORD.iter_unpack(raw):
        index[(z, x, y)] = (offset, length)
    return index  # ruff: ignore[return-in-generator]


def read_tile(index, z: int, x: int, y: int) -> Core[bytes | None]:
    """The tile bytes, or `None` when the archive has no such tile."""
    entry = index.get((z, x, y))
    if entry is None:
        return None  # ruff: ignore[return-in-generator]
    offset, length = entry
    return (yield (offset, length))  # ruff: ignore[return-in-generator]
```

`return` with a value inside a generator is the pattern, not an
accident; ruff's `return-in-generator` check does not know that, hence
the suppressions. A core is driven by one of two ten-line drivers:

```python
from app.provider.sansio import drive, drive_sync

index = drive_sync(read_index(), ranges)          # synchronous reads
index = await drive(read_index(), ranges)         # awaited reads, no thread
```

Test the core with an in-memory `ByteRanges` before touching a bucket.
The suite has one in `tests/test_sansio.py`; it records every request,
so a test can assert not only the answer but how many reads it cost.

## Step 2: bind it to the storage layer

`StorageBackedMixin` gives the provider its data object through the
same layer everything else reads through: local paths and `s3://`,
`gs://`, `az://` URLs are one shape, and the `store_options` of the
provider definition (`region`, `endpoint`, `skip_signature`) travel with
it. Nothing in your provider imports obstore.

```python
class ArchiveTiles(AsyncProviderMixin, StorageBackedMixin, BaseMVTProvider):
    THREAD_SAFE = True
    native_async = True

    def __init__(self, provider_def):
        super().__init__(provider_def)
        self.ranges = self.byte_ranges()      # ByteRanges over `data`
        self._index = None                    # filled on first use, not here
        self._lock = threading.Lock()
```

Keep `__init__` light and free of network calls: pygeoapi instantiates
every tile provider while it generates the OpenAPI document, so a
constructor that reaches the bucket makes document generation slow and
fragile. Read the header on the first request and cache it.

`self.ranges` satisfies the `ByteRanges` Protocol: `read`, `aread`,
`read_many`, `aread_many`. The last two go through obstore's coalescing
reads, which is what you want for directories and indexes: neighbouring
ranges become one request.

## Step 3: give it both faces

```python
    def get_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        index = self._ensure_index_sync()
        return drive_sync(read_tile(index, int(z), int(x), int(y)), self.ranges)

    async def aget_tiles(self, layer, tileset, z, y, x, format_):
        index = await self._ensure_index()
        return await drive(read_tile(index, int(z), int(x), int(y)), self.ranges)

    def _ensure_index_sync(self):
        with self._lock:
            if self._index is None:
                self._index = drive_sync(read_index(), self.ranges)
            return self._index

    async def _ensure_index(self):
        if self._index is None:
            index = await drive(read_index(), self.ranges)
            with self._lock:
                if self._index is None:
                    self._index = index
        return self._index
```

`get_tiles` is pygeoapi's contract: the tilesets and metadata routes,
the OpenAPI generation and any other host keep calling it from the
threadpool. `aget_tiles` is the twin the async tile route awaits. Same
core, two drivers, no duplication of the format logic.

The twin's name is a convention: `a` plus the synchronous method's
name. `aget_tiles` for `get_tiles`, `aquery` and `aget` for a feature
provider. The route finds it by that name; so does `async_view` (below).

Two behaviours the route relies on, both inherited from pygeoapi's own
handler: return `None` for a tile that does not exist within the
configured zoom limits (the client gets `204`), and raise
`ProviderTileNotFoundError` for one outside them (`404`). Any other
`ProviderGenericError` is mapped by its `http_status_code`.

## Step 4: the pygeoapi parts a tile provider must fill in

`BaseMVTProvider` leaves three holes that are easy to miss:

```python
    def get_layer(self):
        return "archive"

    def get_tiles_service(self, baseurl=None, servicepath=None, dirpath=None, tile_type=None):
        # The base method computes the URL and returns None; pygeoapi
        # then iterates over the links. Every concrete provider sets the
        # service URL itself.
        self._service_url = f"{baseurl}{servicepath}"
        return self.get_tms_links()

    def get_html_metadata(self, dataset, server_url, layer, tileset, title, description, keywords, **kwargs):
        ...  # TileJSON and HTML metadata: see MVTTippecanoeProvider for a template
```

`format_` arrives as the provider's own `format_type` (the `format.name`
of the configuration), never the `f=` the client sent; clients must
still send `f=mvt`, because pygeoapi's handler answers `400` without a
format, and the tileset links fastgeoapi publishes carry it.

## Step 5: configure it by dotted path

```yaml
resources:
  places:
    type: collection
    title:
      en: Places
    description:
      en: Places from a tile archive on S3
    keywords:
      en: [places]
    extents:
      spatial:
        bbox: [-180, -90, 180, 90]
        crs: http://www.opengis.net/def/crs/OGC/1.3/CRS84
    providers:
      - type: tile
        name: mypackage.tiles.ArchiveTiles
        data: s3://my-bucket/tiles/places.arc
        store_options:
          region: us-west-2
          skip_signature: true
        options:
          zoom:
            min: 0
            max: 14
          schemes: [WebMercatorQuad]
        format:
          name: pbf
          mimetype: application/vnd.mapbox-vector-tile
```

Any importable class works: pygeoapi treats a `name` with a dot in it
as a dotted path. Because the collection has a `tile` provider, the
`tiles` route group is mounted (routes follow the configuration), and
the tile data route probes the provider once: if it conforms to
`AsyncTileProvider` and declares `native_async`, every tile of that
collection is awaited on the event loop; otherwise it takes pygeoapi's
threadpool path, byte for byte as any other provider.

## The other kinds

**A sync engine, unchanged.** DuckDB, GDAL, a database driver without an
async API: put the mixin first and stop there.

```python
class GeoParquetProvider(AsyncProviderMixin, BaseProvider):
    ...  # query/get as before; native_async stays False
```

Nothing changes for pygeoapi, and the provider is still awaitable
wherever a uniform surface is wanted:

```python
from app.provider.base import async_view

features = await async_view(provider).query(limit=10, bbox=bbox)
```

`async_view` resolves to the twin when the provider is native and to
`asyncio.to_thread(provider.query, ...)` otherwise. It works on any
provider, including one that never saw the mixin.

**A library that is asynchronous itself.** No core of yours: the
library awaits, the storage layer hands it the store. The COG example
below is the model; a service with an async client (an HTTP tile
server, an async database driver) has the same shape, with the sync
face on the service's synchronous client.

**A library that does its own blocking I/O.** If the format library
insists on a `read(offset, length)` callback and cannot be split, keep
the sync face on the library and leave `native_async` at `False`: the
route serves it from the threadpool, honestly. Feeding the library's
pure functions (parsers, lookups) into a core of your own is the way to
a native provider without rewriting the format.

## A real one: a Cloud Optimized GeoTIFF with async-tiff

[async-tiff](https://github.com/developmentseed/async-tiff) by
Development Seed (0.7.2 at the time of writing) reads TIFF metadata and
tiles with ranged requests through an obstore store, and it is
asynchronous only: `TIFF.open` and `fetch_tile` are coroutines. That
makes it the other kind of native provider: the library does the
awaiting, the storage layer hands it the store object, and there is no
parser of ours in between.

```bash
pip install async-tiff
```

The example serves the internal tiles of a web-optimised COG as
`image/jpeg`, **without decoding**. A COG written on the WebMercatorQuad
tiling scheme has 256-pixel tiles that coincide with the map tiles, one
zoom level per overview, so a tile request is one ranged read and one
small splice. GDAL writes such a file with:

```bash
gdal_translate -of COG -co TILING_SCHEME=GoogleMapsCompatible \
  -co COMPRESS=JPEG -co QUALITY=75 -co BLOCKSIZE=256 input.tif places.tif
```

Three facts about the file drive the code. The base IFD carries the
georeferencing (`model_tiepoint`, `model_pixel_scale`) and its pixel
size names the zoom: 156 543.03 m per pixel at zoom 0, halved per level.
Overviews are further IFDs, each half the size of the previous one, and
GDAL's mask band adds IFDs of its own (`new_subfile_type` with bit 4
set) that must be skipped. JPEG tiles share their quantisation and
Huffman tables in the IFD's `jpeg_tables` tag, so a tile on its own is a
JPEG without tables; putting them back is a three-line splice.

```python
import asyncio
import math
import threading

from async_tiff import TIFF
from pygeoapi.models.provider.base import TileMatrixSetEnum
from pygeoapi.provider.tile import BaseTileProvider, ProviderTileNotFoundError

from app.provider.base import AsyncProviderMixin, StorageBackedMixin

HALF_WORLD = 20037508.342789244        # WebMercatorQuad extent, metres
Z0_RESOLUTION = 2 * HALF_WORLD / 256   # metres per pixel at zoom 0, 256-pixel tiles
MASK = 4                               # NewSubfileType bit: transparency mask


def zoom_of(ifd) -> int:
    """The WebMercatorQuad zoom whose resolution this full-resolution IFD has."""
    return round(math.log2(Z0_RESOLUTION / ifd.model_pixel_scale[0]))


def image_levels(tiff) -> dict[int, object]:
    """`{zoom: ifd}` for the image IFDs: masks skipped, overviews by size ratio."""
    base = tiff.ifds[0]
    z0 = zoom_of(base)
    levels = {}
    for ifd in tiff.ifds:
        if (ifd.new_subfile_type or 0) & MASK:
            continue
        levels[z0 - round(math.log2(base.image_width / ifd.image_width))] = ifd
    return levels


def grid_origin(base, zoom: int) -> tuple[int, int]:
    """The WebMercatorQuad column and row of the raster's top-left tile at `zoom`."""
    resolution = Z0_RESOLUTION / 2**zoom
    x0, y0 = base.model_tiepoint[3], base.model_tiepoint[4]
    return round((x0 + HALF_WORLD) / (256 * resolution)), round((HALF_WORLD - y0) / (256 * resolution))


def standalone_jpeg(tile: bytes, tables: bytes | None) -> bytes:
    """A COG stores the JPEG tables once, in the IFD: put them back into the tile."""
    if not tables:
        return tile
    return tile[:2] + tables[2:-2] + tile[2:]   # SOI, the tables without their SOI/EOI, the rest


class CogTiles(AsyncProviderMixin, StorageBackedMixin, BaseTileProvider):
    THREAD_SAFE = True
    native_async = True

    def __init__(self, provider_def):
        super().__init__(provider_def)
        self._tiff = None
        self._lock = threading.Lock()

    async def _open(self):
        if self._tiff is None:
            tiff = await TIFF.open(self.object_key, store=self.native_store, prefetch=65536)
            with self._lock:
                if self._tiff is None:
                    self._tiff = tiff
        return self._tiff

    async def aget_tiles(self, layer, tileset, z, y, x, format_):
        tiff = await self._open()
        ifd = image_levels(tiff).get(int(z))
        if ifd is None:
            raise ProviderTileNotFoundError(f"zoom {z} is not in this archive")
        col0, row0 = grid_origin(tiff.ifds[0], int(z))
        tx, ty = int(x) - col0, int(y) - row0
        across, down = ifd.tile_count
        if not (0 <= tx < across and 0 <= ty < down):
            return None
        tile = await ifd.fetch_tile(tx, ty)
        return standalone_jpeg(bytes(tile.compressed_bytes), ifd.jpeg_tables)

    def get_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        # async-tiff has no synchronous API. pygeoapi calls this from a
        # worker thread where no loop runs; never call it from inside one.
        return asyncio.run(self.aget_tiles(layer, tileset, z, y, x, format_))

    def get_layer(self):
        return "cog"

    def get_tiling_schemes(self):
        return [TileMatrixSetEnum.WEBMERCATORQUAD.value]
```

Two details of the class. `native_store` and `object_key` come from
`StorageBackedMixin`: the obstore store built from `data` and
`store_options`, and the key of the object inside it, which is exactly
the pair `TIFF.open` takes. The provider still imports no obstore. And
the sync face runs the coroutine with `asyncio.run`: async-tiff has no
synchronous API, pygeoapi calls `get_tiles` from a worker thread where
no loop is running, and the rule is the storage bridge's, never from
inside a running loop. The opened `TIFF` is cached on the instance and
reused across calls and across loops; the library's Rust side performs
the reads.

`BaseTileProvider` leaves the same holes as `BaseMVTProvider` in Step
4, minus the MVT metadata: `get_tiles_service` and `get_metadata` are
yours to fill. The configuration is the one of Step 5 with the raster's
format:

```yaml
providers:
  - type: tile
    name: mypackage.tiles.CogTiles
    data: s3://my-bucket/rasters/places.tif
    store_options:
      region: eu-central-1
    options:
      zoom:
        min: 18
        max: 20
      schemes: [WebMercatorQuad]
    format:
      name: jpeg
      mimetype: image/jpeg
```

Run against a file written by the command above, the provider answers a
zoom 20 tile in a fraction of a millisecond from a local store, returns
`None` outside the raster, raises `ProviderTileNotFoundError` for a zoom
the archive lacks, passes the blocking guard, and the recomposed bytes
open as a 256 × 256 three-band JPEG in GDAL. When a request needs
several tiles, `fetch_tiles` fetches them concurrently; and
`header_byte_size` after the first open is the `prefetch` that reads all
the metadata in a single request next time.

## Step 6: prove it does not block

`native_async = True` is a claim, and the suite has a way to check it.
`blockbuster` raises inside the event loop the moment a blocking call
happens there: a socket, a file, `time.sleep`, a synchronous HTTP
client.

```python
import pytest
from blockbuster import blockbuster_ctx

from app.provider.base import async_view


@pytest.mark.asyncio
async def test_the_native_face_never_blocks_the_loop(provider):
    with blockbuster_ctx():
        tile = await async_view(provider).get_tiles(layer="archive", tileset="WebMercatorQuad", z=3, y=2, x=1, format_="pbf")
    assert tile
```

Run it red first: make `aget_tiles` call `time.sleep(0)` once and watch
`BlockingError` appear, then remove it. The threadpool fallback is
allowed to block: it runs in a worker, not on the loop, and the guard
knows the difference.

Two things to know when a test looks at threads. Under Starlette's
`TestClient` the event loop runs in a thread named `asyncio-portal-…`;
the default executor's workers are `asyncio_0`, `asyncio_1`, and so on.
A coroutine cannot run in a worker anyway, so the useful assertion is
the guard above, not the thread name.

## Checklist

- [ ] `AsyncProviderMixin` is the **first** base; the pygeoapi root is
      the last.
- [ ] `native_async = True` only if every `await` in the twin is real.
- [ ] `THREAD_SAFE = True` if the instance caches anything, and a lock
      around what it caches.
- [ ] `__init__` does no network I/O; headers and indexes load on first
      use.
- [ ] `get_tiles_service` is overridden and sets `_service_url`.
- [ ] `None` inside the zoom limits, `ProviderTileNotFoundError`
      outside.
- [ ] A core test in memory, a guard test under `blockbuster_ctx()`,
      both seen red once.
