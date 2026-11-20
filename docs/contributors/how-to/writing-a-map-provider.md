---
icon: material/map-outline
---

# :material-map-outline: Writing a map provider

A native map provider draws the images of `/collections/{collectionId}/map`
and `/collections/{collectionId}/styles/{styleId}/map`. The route awaits it on
the event loop, and it handles everything that does not depend on the engine:
it reads and checks the parameters, applies the limits, queues the maps,
times them out and sets the cache headers. The provider only draws. This page
describes what it must give the
route, what it gets back, and how to check it against the contract suite.
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

from app.interfaces.providers import MapCapabilities, MapLimits
from app.provider.base import AsyncProviderMixin, StorageBackedMixin

WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"


class MyMapProvider(AsyncProviderMixin, StorageBackedMixin, BaseProvider):
    THREAD_SAFE = True
    native_async = True

    @property
    def limits(self) -> MapLimits:
        return MapLimits(
            max_width=2048,
            max_height=2048,
            max_pixels=None,
            concurrent=1,
            waiting=8,
            timeout=30.0,
        )

    @property
    def capabilities(self) -> MapCapabilities:
        return MapCapabilities(crs=(WEB_MERCATOR,), formats=("png",))

    async def arender_map(self, *, style, bbox, width, height, crs,
                          transparent, format_, datetime_, subsets) -> bytes: ...

    async def aget_version(self, *, style, bbox, width, height, crs,
                           transparent, format_, datetime_, subsets) -> str | None: ...

    def close(self) -> None: ...
```

`limits` gives the largest map the engine draws, how many maps it draws at
the same time, how many more may wait for a slot, and how many seconds a map
may take, the wait included. The route publishes the sizes in the OpenAPI
document as the `maximum` of `width` and `height`. When the server ceiling is
smaller (`FASTGEOAPI_MAPS_MAX_WIDTH`, `FASTGEOAPI_MAPS_MAX_HEIGHT`,
`FASTGEOAPI_MAPS_MAX_PIXELS`), the ceiling applies, and a warning at startup
names the collection.

`capabilities` gives the CRSs the engine draws in and the values of `f` it
encodes. The document publishes them as the `crs` and `f` enums. A request
for anything else gets a 400 before the provider is called.

`arender_map` returns the encoded image. `aget_version` returns the version
of the image `arender_map` would draw for the same arguments, without drawing
it. The route builds the `ETag` from that version, and answers 304 to a
request that already has the map. The version must change whenever the image
can change: the data, the definition, the style or the engine. Return None
when the version of the data is unknown; the map then goes without cache
headers.

The map served with an `ETag` must be drawn from the data that `ETag` names.
Read the data pinned to the version you return, as `CachedRanges` does with
`if_match`, and fail rather than mix two versions when the data changes during
a draw. The route reads the version again after the draw and drops the cache
headers when it moved.

`close()` must not block, and may be called more than once. The plugin cache
calls it on the instances a reload drops, from the reloading thread, while the
old sub-app may still be drawing with them. A provider that has to close
something asynchronously schedules it from there.

## What it receives

The route reads the query, checks it and passes typed arguments, always by
keyword:

| Argument          | What the route has already done                                                                                                                                |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `style`           | `None` for the default style, or the `{styleId}` of the path. An unknown name is the provider's to refuse with `ProviderItemNotFoundError`, which answers 404. |
| `bbox`            | Four finite numbers, moved from `bbox-crs` into `crs` and clipped to the extent of `crs`. A box entirely outside it answers 204 without calling the provider.  |
| `width`, `height` | Positive integers within the published limits.                                                                                                                 |
| `crs`             | One of the URIs in `capabilities.crs`, spelled as published.                                                                                                   |
| `transparent`     | A boolean.                                                                                                                                                     |
| `format_`         | One of `capabilities.formats`.                                                                                                                                 |
| `datetime_`       | The `datetime` of the request, checked against the temporal extent of the collection, or None.                                                                 |
| `subsets`         | The `subset` values by additional dimension, or None.                                                                                                          |

`bbox-crs` never reaches the provider. `aget_version` receives the same
arguments as `arender_map`.

## What it leaves to the route

The provider does not answer 400 or 413: the route has checked the parameters
before the call. It does not queue maps and does not time them out: the route
admits at most `concurrent` maps at once and `waiting` more, answers 503 with
`Retry-After` beyond that, and 504 past `timeout`. A map that answered 504 goes
on drawing and keeps its slot until the engine finishes, because cancelling a
draw may kill the engine's process. The provider raises
`ProviderGenericError` when the engine fails, which answers 500.

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
