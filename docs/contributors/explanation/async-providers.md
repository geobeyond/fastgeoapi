---
icon: material/waves
---

# :material-waves: Two faces for a provider

pygeoapi's provider contract is synchronous: `query`, `get`,
`get_tiles` are plain methods, and the API layer calls them from a
threadpool. fastgeoapi keeps that contract exactly as it is and adds an
asynchronous face beside it. This page is about why the addition is
shaped the way it is; [Writing an async provider](../how-to/writing-an-async-provider.md)
is about doing it.

## The threadpool is smaller than it looks

Every pygeoapi handler runs through `loop.run_in_executor(None, ...)`,
the default executor. Python sizes it as `min(32, cpu_count + 4)`: on a
one-vCPU machine, the kind the demo runs on, that is **five threads**.
Five requests waiting on the network and the sixth is queued, whatever
route it asked for.

For a CPU-bound engine this is the right shape. DuckDB scanning a
GeoParquet dataset is work, and a thread is where work goes; awaiting
it would change nothing but the syntax. For a source read piecewise
over the network it is the wrong shape. A tile from a PMTiles archive on
S3 costs one to three small ranged reads, each a round trip; a map view
asks for twenty to fifty tiles at once. In the threadpool those are
served five at a time. Awaited, they are all in flight together and the
limit is bandwidth.

So the question was never "sync or async". It was how to let a provider
be awaited where waiting is the cost, without forcing every provider to
pretend.

## Extend, do not replace

The first constraint is pygeoapi itself. Its API reads attributes off
the provider instance, calls `get_layer()` inline while building the
arguments for `get_tiles`, instantiates every tile provider while it
generates the OpenAPI document, and expects one constructor argument.
That is a contract by attribute and by call, and a class must honour it:
inheriting the pygeoapi root is not optional.

The second constraint is that pygeoapi has families, features and tiles
and coverages, with different method names and different root classes
(`BaseTileProvider` does not even derive from `BaseProvider`). The
first draft of this design had one fastgeoapi base per family. It was
dropped, for a reason worth keeping: it duplicated knowledge pygeoapi
already owns, and every method upstream added would have needed a twin
here.

What remained is a single mixin that knows nothing about pygeoapi. It
captures the provider definition, declares `native_async`, and offers a
helper to run a blocking callable off the loop. The concrete class pairs
it with whichever root the family needs, mixin first, because pygeoapi's
roots do not call `super().__init__()`. The family knowledge lives in
two places that have to know it anyway: the Protocols the router checks,
and the router.

## Declared, not inspected

`native_async` is a class attribute a provider sets to `True`. It would
have been possible to inspect instead: is `aget_tiles` a coroutine
function? But a coroutine that wraps `asyncio.to_thread(self.get_tiles)`
is a coroutine function too, and so is one that calls a synchronous HTTP
client inside an `async def`. Inspection cannot tell honest `await` from
dressed-up blocking. A declaration can be wrong, but it can be tested,
and the suite has a guard that does exactly that: `blockbuster` raises
the moment a blocking call happens on the loop.

The declaration also decides who writes what. A native provider writes
its async twins, named `a` plus the sync method. Everyone else writes
nothing: `async_view(provider)` gives any provider an awaitable face,
running the sync method in a thread when there is no twin to call. That
adapter is composition where inheritance would have put a generated
method on every class, and it works on providers that never saw the
mixin at all.

## One route, awaited where it counts

The asynchronous face reaches HTTP through a single route: tile data.
It lives in the same route table as everything else, tagged with the
`tiles` group, so it is mounted only when the configuration has a tile
provider, passes through the same authentication middleware, and is
rebuilt on every reload. It is placed before pygeoapi's own tile route,
which is how it wins for the same path.

Per request it does one of two things. If the collection's provider
conforms to `AsyncTileProvider` and declares `native_async`, the tile
is awaited on the loop with the same status mapping pygeoapi uses: `204`
for a tile that does not exist within limits, `404` for one outside
them, the provider's own `http_status_code` for anything else. If not,
the request goes to pygeoapi's handler in the threadpool, byte for byte
as before. The probe that decides runs once per configured collection,
off the loop, because it instantiates the provider.

Features have no such route yet, and deliberately. pygeoapi's items
handler is hundreds of lines of parameter parsing and output formatting,
and the one feature backend fastgeoapi ships is DuckDB, which belongs in
a thread. The mixin gives feature providers `aquery` today; the route
will follow a backend that pays for it.

## A parser that never does I/O

The formats worth awaiting are read by ranges: PMTiles, cloud-optimised
GeoTIFF, FlatGeobuf. Their parsers need "these bytes at this offset",
nothing more. Writing the parser as a generator that yields
`(offset, length)` and receives bytes makes it indifferent to how the
bytes arrive. Two drivers of ten lines each feed it, one with
synchronous reads and one with awaited reads, and the provider's two
faces become two one-line methods over the same core.

The alternative, a sync method that runs its async twin with
`asyncio.run`, is not the general mechanism. It works in a threadpool
worker, where no loop is running, but it builds and tears down a fresh
event loop on every call and leaves the worker without a current loop
until pygeoapi resets it on the next request; inside a running loop it
fails outright. It remains the fallback for a library that is
asynchronous only, with the rule the storage layer's bridge already
states: never from inside a running loop.

## The storage layer learnt ranges

Everything fastgeoapi reads goes through one `ObjectStore` Protocol,
with a sync and an async method for each operation. Ranged reads joined
it with this design: `get_range` and `get_ranges`, with their `a`
twins. `get_ranges` matters more than it looks: the backend coalesces
neighbouring ranges into one request, and a directory lookup is exactly
a handful of neighbouring ranges.

A provider does not touch the store directly. `StorageBackedMixin`
resolves the `data` URL and the `store_options` from the captured
definition and hands back a `ByteRanges` bound to that one object. The
parser sees offsets; the mixin sees a key in a store; only the storage
layer sees a bucket. A library that reads through obstore itself, as
async-tiff does, gets the store object and the key from the same mixin
and does its own ranged reads: the provider still imports no obstore.

## What this does not promise

"Fully asynchronous" is a property of the whole chain, not of a
provider. One middleware fastgeoapi can enable, the OPA authorizer from
`fastapi-opa`, still performs a blocking HTTP call inside its
`async def __call__`; with it enabled, every request stops the loop for
the duration of the policy decision. The guard in the test suite will
report it rather than hide it, and the fix belongs upstream.
