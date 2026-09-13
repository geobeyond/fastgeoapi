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
[async-geotiff](https://pypi.org/project/async-geotiff/), a library that is
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

## A real one: a Cloud Optimized GeoTIFF with async-geotiff

[async-geotiff](https://developmentseed.org/async-geotiff/) by
Development Seed (0.5.1 at the time of writing) is a GeoTIFF and
[COG](https://cogeo.org/) reader that fetches metadata, overviews and
tiles with ranged requests, and it is **asynchronous only**: `open`,
`read` and `fetch_tile` are all coroutines. That makes it the other kind
of native provider: the library does the awaiting, and there is no
parser of ours in between.

```bash
pip install async-geotiff
```

It reads through an object called a `Store`, and that is the whole
integration: the protocol it asks for is two methods, `get_range_async`
and `get_ranges_async`, which is exactly what the store behind
`StorageBackedMixin` already offers. `self.native_store` satisfies it as
it is — the provider imports no object-storage library at all.

The example serves 256-pixel PNG tiles on WebMercatorQuad from a COG
written on the matching tiling scheme, which GDAL produces with:

```bash
gdal_translate -of COG -co TILING_SCHEME=GoogleMapsCompatible \
  -co COMPRESS=JPEG -co QUALITY=75 -co BLOCKSIZE=256 input.tif places.tif
```

Two facts about such a file drive the code. Its pixel size names a zoom —
156 543.03 m per pixel at zoom 0, halved per level — so the base image is
one zoom and each overview is the next one down. And its tiles do **not**
always line up with the map's: the tiling scheme aligns the base level,
but a raster whose top-left falls on an odd tile index there sits half a
tile off one level up. So the example does not chase internal tiles; it
asks for the window the map tile covers, which is right at any alignment
and is what the library is for.

```python
import asyncio
import math
import struct
import threading
import zlib

import numpy as np
from async_geotiff import GeoTIFF, Window
from pygeoapi.models.provider.base import TileMatrixSetEnum
from pygeoapi.provider.tile import BaseTileProvider, ProviderTileNotFoundError

from app.provider.base import AsyncProviderMixin, StorageBackedMixin

HALF_WORLD = 20037508.342789244        # WebMercatorQuad extent, metres
Z0_RESOLUTION = 2 * HALF_WORLD / 256   # metres per pixel at zoom 0, 256-pixel tiles


def png(bands) -> bytes:
    """The smallest honest PNG: 8-bit RGB, no filtering, band-first input."""
    height, width = bands.shape[1:]
    raw = b"".join(b"\0" + bands[:, row, :].T.tobytes() for row in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


class CogTiles(AsyncProviderMixin, StorageBackedMixin, BaseTileProvider):
    THREAD_SAFE = True
    native_async = True

    def __init__(self, provider_def):
        super().__init__(provider_def)
        self._cog = None
        self._lock = threading.Lock()

    async def _open(self):
        if self._cog is None:
            cog = await GeoTIFF.open(self.object_key, store=self.native_store)
            with self._lock:
                if self._cog is None:
                    self._cog = cog
        return self._cog

    def _level(self, cog, zoom: int):
        """The base image or the overview whose resolution is this zoom's."""
        base = round(math.log2(Z0_RESOLUTION / cog.res[0]))
        if zoom == base:
            return cog
        index = base - zoom - 1
        if not 0 <= index < len(cog.overviews):
            raise ProviderTileNotFoundError(f"zoom {zoom} is not in this file")
        return cog.overviews[index]

    async def aget_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        cog = await self._open()
        try:
            zoom, col, row = int(z), int(x), int(y)
        except (TypeError, ValueError):
            raise ProviderTileNotFoundError(f"tile {z}/{x}/{y} is not a tile")
        level = self._level(cog, zoom)

        # The tile's top-left corner, in this level's pixel space.
        size = 256 * (Z0_RESOLUTION / 2**zoom)
        row_off, col_off = level.index(col * size - HALF_WORLD, HALF_WORLD - row * size)

        # Clipped to the raster: a window may not start outside it, and a
        # tile at the edge is partly empty.
        left, top = max(col_off, 0), max(row_off, 0)
        right, bottom = min(col_off + 256, level.width), min(row_off + 256, level.height)
        if left >= right or top >= bottom:
            return None

        patch = await level.read(
            window=Window(col_off=left, row_off=top, width=right - left, height=bottom - top)
        )
        canvas = np.zeros((cog.count, 256, 256), dtype=patch.data.dtype)
        canvas[:, top - row_off : bottom - row_off, left - col_off : right - col_off] = patch.data
        return png(canvas)

    def get_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        # async-geotiff has no synchronous API. pygeoapi calls this from a
        # worker thread where no loop runs; never call it from inside one.
        return asyncio.run(self.aget_tiles(layer, tileset, z, y, x, format_))

    def get_layer(self):
        return "cog"

    def get_tiling_schemes(self):
        return [TileMatrixSetEnum.WEBMERCATORQUAD.value]
```

Three details of the class. `native_store` and `object_key` come from
`StorageBackedMixin` — the store built from `data` and `store_options`,
and the key of the object inside it — which is exactly the pair
`GeoTIFF.open` takes. The sync face runs the coroutine with
`asyncio.run`: the library has no synchronous API, pygeoapi calls
`get_tiles` from a worker thread where no loop is running, and the rule
is the storage bridge's, never from inside a running loop. And the opened
`GeoTIFF` is cached on the instance and reused across calls and across
loops; the library's Rust side performs the reads.

What the library gives back is a `RasterArray`: `.data` is a NumPy array
shaped `(bands, height, width)`, with `.mask`, `.bounds`, `.crs`,
`.transform` and `.index` beside it. Turning pixels into a picture is the
provider's business, which is what the fifteen-line `png` is doing; a
deployment that wants JPEG or WebP reaches for an encoder instead.

`BaseTileProvider` leaves the same holes as `BaseMVTProvider` in Step 4,
minus the MVT metadata: `get_tiles_service` and `get_metadata` are yours
to fill. The configuration is the one of Step 5 with the raster's format:

```yaml
providers:
  - type: tile
    name: mypackage.tiles.CogTiles
    data: s3://my-bucket/rasters/places.tif
    store_options:
      region: eu-central-1
    options:
      zoom:
        min: 11
        max: 15
      schemes: [WebMercatorQuad]
    format:
      name: png
      mimetype: image/png
```

Run against a file written by the command above — 2304 × 2304 pixels,
four overviews, zooms 11 to 15 — the provider answers a tile in **3 to
10 ms** from a local store at every one of those zooms, returns `None`
outside the raster, raises `ProviderTileNotFoundError` for a zoom the
file lacks and for a URL template pasted literally, and the bytes open as
a 256 × 256 three-band PNG in GDAL. Four tiles awaited together under the
blocking guard of Step 6 pass without a complaint.

Two knobs worth knowing. `GeoTIFF.open` takes a `prefetch` (32 KiB by
default) — the first read, sized to swallow the whole header so the
metadata costs one request. And `fetch_tiles` fetches several internal
tiles concurrently, for a provider that does match them one to one.

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
