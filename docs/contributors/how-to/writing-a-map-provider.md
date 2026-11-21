---
icon: material/map-outline
---

# :material-map-outline: Writing a map provider

A native map provider draws the images of `/collections/{collectionId}/map`
and `/collections/{collectionId}/styles/{styleId}/map`. The route awaits it on
the event loop, and it handles everything that does not depend on the engine:
it reads and checks the parameters, applies the limits and sets the cache
headers. The provider draws the maps, and its queue and timeouts are its own.
This page describes what it must give the route, what it gets back, and how to
check it against the contract suite.
[Writing an async provider](writing-an-async-provider.md) covers the general
shape of a provider and the mixins.

## What the provider gives

The contract is the Protocol `AsyncMapProvider` in
`app/interfaces/providers.py`. A provider class that sets
`native_async = True` must define all of its members. When one is missing,
the configuration is refused at startup and at every reload, with an error
that names the class and the member. A reload keeps the old configuration in
service.

```python
from pygeoapi.provider.base import BaseProvider

from app.interfaces.providers import (
    MapCapabilities,
    MapFormat,
    MapLimits,
    MapParameters,
    NotRenderedMap,
    RenderedMap,
)
from app.provider.base import AsyncProviderMixin, StorageBackedMixin

WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"


class MyMapProvider(AsyncProviderMixin, StorageBackedMixin, BaseProvider):
    THREAD_SAFE = True
    native_async = True

    @property
    def limits(self) -> MapLimits:
        return MapLimits(max_width=2048, max_height=2048)

    @property
    def capabilities(self) -> MapCapabilities:
        return MapCapabilities(
            crs=(WEB_MERCATOR,),
            default_crs=WEB_MERCATOR,
            formats=(MapFormat.PNG,),
            styles=("night",),
        )

    async def arender_map(self, parameters: MapParameters) -> RenderedMap | NotRenderedMap: ...

    async def aget_version(self, parameters: MapParameters) -> str | None: ...

    def close(self) -> None: ...
```

`limits` gives the largest map the engine draws. `max_pixels`, the largest
`width * height`, is optional: set it only when the engine has an area limit
of its own. The route publishes the sizes in the OpenAPI document as the
`maximum` of `width` and `height`. When the server's limits are
smaller (`FASTGEOAPI_MAPS_MAX_WIDTH`, `FASTGEOAPI_MAPS_MAX_HEIGHT`,
`FASTGEOAPI_MAPS_MAX_PIXELS`), they apply, and a warning at startup names
the collection.

`capabilities` gives the CRSs the engine draws in, the default CRS, the
encodings it draws maps in and the names of its styles. A CRS is an OGC CRS URI, such as
`http://www.opengis.net/def/crs/EPSG/0/3857`, that pyproj knows; an
encoding is a member of `MapFormat`, one per encoding class of OGC API -
Maps (PNG, JPEG, JPEG XL, TIFF, SVG and HTML). A configuration whose
provider declares anything else is refused at startup, with an error that
names the class and the value. The document publishes them as the `crs` and
`f` enums, and a request for anything else gets a 400 before the provider
is called. A `{styleId}` that is not among the styles gets a 404, also before
the call.

`default_crs` is the CRS of a map whose request names no `crs`, and must be
one of `crs`; a configuration where it is not is refused at startup. The
provider chooses it when it is built, usually the `storage_crs` of its
definition when it draws in it: the route reads no CRS from the definition.
The order of `crs` does not matter. The route publishes `default_crs` as the
default of the `crs` parameter and first in the collection's `crs` list, and
as the collection's `storageCrs` when it is not CRS84.

The provider declares no conformance classes. `/conformance` derives them
from the capabilities: `core`, `collection-map`, `crs` and the class of each
encoding. The collection description lists the CRSs in `crs`, with
`storageCrs` and `storageCrsBbox` when `default_crs` is not CRS84, and links
one map per encoding.

`arender_map` returns a `RenderedMap`: the encoded image and the version it
was drawn from. `aget_version` returns the version of the image `arender_map`
would draw for the same parameters, without drawing it. The route builds the
`ETag` from these versions: it answers 304 to a request that already has the
map, and gives a drawn map the `ETag` of its own version. The version must
change whenever the image can change: the data, the definition, the style or
the engine. Return None when the version of the data is unknown; the map then
goes without cache headers.

The map must be drawn from the data its version names. Read the data pinned to
one version, as `CachedRanges` does with `if_match`, and return that version
even when a newer one arrives during the draw. Fail rather than mix two
versions.

The map covers exactly `parameters.bbox` in `parameters.crs`: the route
declares both in `Content-Bbox` and `Content-Crs`.

A `RenderedMap` may also carry `extra_headers`, response headers of the
provider's own such as `X-Render-Time`. The route sends them after its own
headers are set, and keeps its value for a name it has already set. It drops
the headers that describe the image or its caching, whether or not it sets
them for that map: `Content-Type`, `Content-Length`, `Content-Encoding`,
`Content-Crs`, `Content-Bbox`, `Content-Datetime`, `Cache-Control`, `ETag`,
`Expires`, `Last-Modified`, `Vary` and `Retry-After`. A 304 carries only what
the route sets, and a map without a version must stay out of caches. Each
header the route does not send is logged as a warning.

`close()` must not block, and may be called more than once. The plugin cache
calls it on the instances a reload drops, from the reloading thread, while the
old sub-app may still be drawing with them. A provider that has to close
something asynchronously schedules it from there.

## What it receives

The route reads the query, checks it and passes one `MapParameters` object,
whose fields are:

| Field             | What the route has already done                                                                                                                                    |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `style`           | `None` for the default style, or one of `capabilities.styles`. The route answers 404 to any other `{styleId}`.                                                     |
| `bbox`            | Four finite numbers, moved from `bbox-crs` into `crs` and clipped to the extent of `crs`. A box entirely outside it answers 204 without calling the provider.      |
| `width`, `height` | Positive integers within the published limits.                                                                                                                     |
| `crs`             | One of the URIs in `capabilities.crs`, spelled as published.                                                                                                       |
| `transparent`     | A boolean.                                                                                                                                                         |
| `format_`         | One of `capabilities.formats`.                                                                                                                                     |
| `datetime_`       | An instant as a `datetime`, or a `TimeInterval` whose open end is None, in UTC and checked against the temporal extent of the collection; None without `datetime`. |
| `subsets`         | The `subset` values by additional dimension, or None.                                                                                                              |
| `vendor_params`   | The query parameters OGC API - Maps does not define, by name, as the client sent them; empty when there are none. The route does not check them.                   |

`bbox-crs` never reaches the provider. `aget_version` receives the same
object as `arender_map`. The `ETag` depends on `vendor_params`, so a provider
that reads one only has to change the image; the version may stay the same.

## What it leaves to the route

The provider does not answer 400, 404 or 413: the route has checked the
parameters before the call. The provider and its engine decide how many maps
are drawn at once and how long a map may wait. When the server is too busy to
draw the map now, `arender_map` returns a `NotRenderedMap` with the status of
the answer and, when it knows them, the seconds before a retry. The route
answers with that status, and with `Retry-After` when the seconds are there.
The MapLibre provider answers a full
queue with 503 and `Retry-After: 5`, and a map past its timeout with 504.

A fault of the engine is raised, as pygeoapi's providers do:
`ProviderGenericError` answers 500, and the route logs its traceback.

## Running the contract suite

`tests/maps_contract` checks these promises once for every native map
provider. Each entry of `PROVIDERS` in `tests/maps_contract/conftest.py`
builds the definition of a provider over a PMTiles archive. Every test of the
folder runs once per entry, against a collection named `under_test` with a
style named `night`, `max_size` 1024 and the HTTP cache on:

```python
def _my_provider(archive: Path, **options: Any) -> dict:
    return {
        "type": "map",
        "name": "app.provider.my_maps.MyMapProvider",
        "data": str(archive),
        "storage_crs": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "options": options,
        "format": {"name": "png", "mimetype": "image/png"},
    }


PROVIDERS: dict[str, Callable[..., dict]] = {
    "maplibre": _maplibre,
    "maplibre-native": _maplibre_native,
    "my-provider": _my_provider,
}
```

An entry that draws with MapLibre Native goes in `NEEDS_RENDERER` as well:
its tests are marked `renderer` and skipped where mlnative is missing. An
engine of another kind that is not installed everywhere needs a marker and a
skip of its own.

```bash
uv run --no-sync pytest tests/maps_contract -q
```

The suite checks the status of a map (404, 413, 400, 200), the published
maximum and CRSs against those the route applies, the `ETag` and the 304, the
new `ETag` and map when the archive is replaced behind the range cache, and
the `close()` on reload. The checks that look inside the renderer run only for
the `maplibre` entry, whose fake renderer records what it draws. The other
entries are checked by their answers, and MapLibre Native also by the pixels
of the map drawn after the archive is replaced.
