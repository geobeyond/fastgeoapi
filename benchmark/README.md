# Vector tile benchmark: martin tile provider vs martin vs pygeoapi PMTiles

This compares three ways fastgeoapi can serve the **same Lazio road segments**
as Mapbox Vector Tiles. All three run against one fixed, seeded tile list,
with the same load generator, on the same machine.

| Case                          | Endpoint                                                                         | Source                                                        | Tiles made                                       |
| ----------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------ |
| **A. fastgeoapi + martin-py** | `/geoapi/collections/lazio-roads-martin/tiles/WebMercatorQuad/{z}/{y}/{x}?f=mvt` | `s3://fastgeoapi-demo/overture/transportation-lazio.parquet`  | on request, by Martin's DuckDB tiler, in-process |
| **B. standalone `martin`**    | `/transportation-lazio/{z}/{x}/{y}`                                              | same GeoParquet, same martin config                           | on request, same tiler, no Python                |
| **C. pygeoapi PMTiles**       | `/geoapi/collections/lazio-roads-tiles/tiles/WebMercatorQuad/{z}/{y}/{x}?f=mvt`  | `s3://fastgeoapi-demo/tiles/lazio-roads.pmtiles` (tippecanoe) | ahead of time; read by byte range                |

- **A** is the martin tile provider (`app.provider.martin.MartinTilesProvider`) serving the
  `lazio-roads-martin` collection through the OGC API Tiles route, like any other tile collection.
- **A vs B** isolates what the Python side costs: the OGC API route, the tile provider (its zoom
  limits and the version check of the data) and the PyO3 call. The tiler, its config and the data
  are identical: B's config is written from A's provider definition.
- **A/B vs C** compares generating tiles from GeoParquet when they're requested with serving
  tiles built ahead of time. The tile _content_ differs (tippecanoe simplifies and drops
  features), so this is a comparison of serving strategies, not a like-for-like one.

Both objects are public and unsigned on Tigris (`t3.storage.dev`). Using one staged file of
known size, rather than a whole Overture release, keeps run-to-run variance down to the
network and the tiler.

## Files

| File                                                     | What it is                                                                           |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| [`pygeoapi-config.bench.yml`](pygeoapi-config.bench.yml) | pygeoapi config: `lazio-roads-martin` (A), `lazio-roads-tiles` (C), `lazio-roads` (features) |
| [`martin.yaml`](martin.yaml)                             | B's Martin config, written from A's provider definition (see step 1)                         |
| [`martin-https.yaml`](martin-https.yaml)                 | same object over public HTTPS, for martin 1.16.1 (no object-store keys)                      |
| [`../scripts/bench_tiles.py`](../scripts/bench_tiles.py) | `config`: write `martin.yaml` · `run`: fetch the tile list from each target, report          |
| [`results/`](results/)                                   | raw output of the runs below                                                                 |

## Prerequisites

```shell
uv sync --extra martin              # martin-py; build the wheel with --release
cargo build --release -p martin     # in the martin repo, for case B
```

Use release builds for both. A debug build of martin-py or martin decides the result by itself.

## 1. Write B's Martin config

```shell
uv run python scripts/bench_tiles.py config \
    --pygeoapi-config benchmark/pygeoapi-config.bench.yml \
    --resource lazio-roads-martin \
    --output benchmark/martin.yaml
```

(These are the defaults.) This writes the Martin config the martin tile provider of
`lazio-roads-martin` loads in-process — read with the same code
(`MartinTilesConfig.from_provider_def`), the Tigris `store_options` translated to Martin's
object-store keys — so standalone martin serves exactly the same source.

> [!IMPORTANT]
> **Keep martin's tile cache off on both sides.** martin's default tile cache answers every
> warm pass from memory: [`results/auto-mode-cache-on.txt`](results/auto-mode-cache-on.txt)
> shows warm p50 **1 ms** with the cache against **324 ms** for an uncached martin. The provider
> carries `cache_size_mb: 0` in its options, which becomes `cache.size_mb: 0` in `martin.yaml`;
> `config` warns when it is missing.

## 2. Start the servers

Restart both servers before every run if the first pass is meant to be cold.

```shell
# A and C: one fastgeoapi process serves both
DEV_PYGEOAPI_CONFIG=benchmark/pygeoapi-config.bench.yml \
MARTIN_PY_POLL_DIRECTLY= RUST_LOG=warn \
uv run fastgeoapi run --host 127.0.0.1 --port 5999

# B
RUST_LOG=warn ../martin/target/release/martin \
    --config benchmark/martin.yaml --listen-addresses 127.0.0.1:3999
```

- Don't use `--reload`.
- Unset `MARTIN_PY_POLL_DIRECTLY`; it's a debugging aid for the config load.
- martin loads the source at A's first tile, not at startup: the readiness check below (or the
  TileJSON at `/geoapi/collections/lazio-roads-martin/tiles/WebMercatorQuad/metadata?f=tilejson`)
  pays for it, so the first pass doesn't.

## 3. Run

```shell
uv run python scripts/bench_tiles.py run \
  --target 'A-provider=http://127.0.0.1:5999/geoapi/collections/lazio-roads-martin/tiles/WebMercatorQuad/{z}/{y}/{x}?f=mvt' \
  --target 'B-martin=http://127.0.0.1:3999/transportation-lazio/{z}/{x}/{y}' \
  --target 'C-pmtiles=http://127.0.0.1:5999/geoapi/collections/lazio-roads-tiles/tiles/WebMercatorQuad/{z}/{y}/{x}?f=mvt' \
  --zoom 10 --zoom 11 --zoom 12 --zoom 13 --per-zoom 25 \
  --concurrency 1 --concurrency 4 --concurrency 16 --repeat 1 \
  | tee benchmark/results/abc-cache-off.txt
```

Mind the tile order: Martin's path (B) is `{z}/{x}/{y}`, while OGC API - Tiles (A and C) uses
`{tileMatrix}/{tileRow}/{tileCol}`, which is `{z}/{y}/{x}`. The zooms stop at 13 because
that's the PMTiles archive's `maxzoom`.

For each target the script runs:

1. **one first pass** over all tiles at the first concurrency level;
2. **`--repeat` warm passes** at every concurrency level.

Every pass reports p50, p95 and p99 latency, requests per second, bytes, and HTTP status
counts. The script then checks **parity**: every target's tile sizes are compared with the
first target's.

| Option                 | Default               | Meaning                                                   |
| ---------------------- | --------------------- | --------------------------------------------------------- |
| `--bbox`               | `11.4,41.2,14.1,42.9` | west,south,east,north; Lazio, the extent of both datasets |
| `--zoom` (repeatable)  | 10 … 14               | zoom levels sampled                                       |
| `--per-zoom`           | 40                    | tiles sampled at random per zoom                          |
| `--seed`               | 42                    | same seed, same tiles, same order                         |
| `--concurrency` (rep.) | 1, 4, 16              | requests in flight per warm pass                          |
| `--repeat`             | 2                     | warm passes per concurrency level                         |
| `--tolerance`          | 0.02                  | tile size difference still counted as on par              |

All requests send `Accept-Encoding: identity`. fastgeoapi and standalone Martin would both
compress if asked, but not alike, and a byte count should mean the same thing on every
target. An empty tile answers `204` on A and C.

## Results

> [!NOTE]
> The runs up to 2026-11-18 predate the martin tile provider. Case A was then the `/martin-wrapper`
> mount, since removed: a Starlette sub-app calling martin-py on martin's own `{z}/{x}/{y}` paths,
> loading the same `martin.yaml` as B. Their numbers are kept as history; the provider's are in
> [Martin tile provider, 2026-11-24](#martin-tile-provider-2026-11-24).

Run on 2026-10-27, on an AMD Ryzen 7 8845HS (16 threads, 92 GB RAM, Linux) with server and
load generator on the same host. The data stayed on Tigris. The run used 100 tiles (25 per
zoom, z10–z13, seed 42) and the DuckDB pool default of `pool_size: 4`. Raw output is in
[`results/abc-cache-off.txt`](results/abc-cache-off.txt).

| Case      | Pass      |     p50 |     p95 |     p99 | req/s |    MB | status           |
| --------- | --------- | ------: | ------: | ------: | ----: | ----: | ---------------- |
| A wrapper | first c=1 |  323 ms | 1075 ms | 1423 ms |   2.6 | 25.28 | 200 ×100         |
|           | warm c=1  |  321 ms |  377 ms |  507 ms |   3.0 |       |                  |
|           | warm c=4  |  637 ms | 1484 ms | 7414 ms |   4.4 |       |                  |
|           | warm c=16 | 2498 ms | 2978 ms | 3346 ms |   6.1 |       |                  |
| B martin  | first c=1 |  322 ms |  961 ms | 1603 ms |   2.5 | 25.28 | 200 ×100         |
|           | warm c=1  |  325 ms |  372 ms |  534 ms |   3.0 |       |                  |
|           | warm c=4  |  591 ms | 1657 ms | 6894 ms |   4.7 |       |                  |
|           | warm c=16 | 2673 ms | 3426 ms | 3689 ms |   5.8 |       |                  |
| C PMTiles | first c=1 |  223 ms |  670 ms | 1184 ms |   3.9 |  8.32 | 200 ×86, 204 ×14 |
|           | warm c=1  |  197 ms |  410 ms |  726 ms |   4.9 |       |                  |
|           | warm c=4  |  188 ms |  560 ms |  825 ms |  17.1 |       |                  |
|           | warm c=16 |  178 ms |  477 ms |  671 ms |  70.3 |       |                  |

Parity:

- A vs B: **0** tiles differ by more than 2% (max 0.1%); both return the same 100 tiles.
- A vs C: 83 tiles differ by more than 2% (max 86.7%); 14 tiles exist only in A.

### Reading the results

- **The Python wrapper costs nothing measurable.** A and B are within run-to-run noise at
  every concurrency level, and their tiles match. Generating the tile in DuckDB plus the reads
  from Tigris take all the time. Starlette, the threadpool and PyO3 don't show up.
- **Generating tiles on request stops scaling at the DuckDB pool size.** From c=1 to c=16,
  A and B only double their throughput (3 → 6 req/s) while p50 goes from 0.3 s to 2.5 s.
  With `pool_size: 4`, at most four tile queries run at once and the rest wait. The c=4 p99
  of about 7 s is a few tiles that each take seconds. Raising `duckdb.pool_size` (and `threads`)
  in `martin.yaml` is the first thing to try. A then also needs Starlette's threadpool (40
  by default) to stay above it.
- **Pre-built PMTiles scale almost linearly:** 4.9 → 70 req/s from c=1 to c=16 at a flat
  p50 of about 180–200 ms. That's one or two byte-range GETs to Tigris per tile, and nothing
  to compute. The tiles are about 3× smaller (8.3 MB against 25.3 MB) because tippecanoe
  simplifies and drops features per zoom. The 14 `204 No Content` responses are tiles the
  archive left empty while the GeoParquet path still had segments for them. So C is faster
  and also not the same map.
- **The first pass is barely colder than the warm ones** (p50 323 ms against 321 ms) because the
  source is a single file whose footer Martin reads at startup. A multi-file Overture
  release would show a much larger first-pass penalty.

### Re-run on 2026-11-18

Same host, same command and parameters as above. What changed:

- **A** uses the martin-py **v0.1.1** release wheel (the extra was then named `martin_wrapper`), linked against
  crates.io martin `2.0.0-beta.7`.
- **B** is martin `2.0.0-beta.7` from crates.io, built in release mode with only DuckDB support
  (`cargo install martin --version =2.0.0-beta.7 --locked --no-default-features --features unstable-duckdb`),
  so A and B run the same martin version.
- fastgeoapi ran with `DEV_JWKS_ENABLED=false DEV_API_KEY_ENABLED=false DEV_OPA_ENABLED=false`.
  The wrapper was by then behind the same auth chain as `/geoapi`, and `bench_tiles.py` sends no
  credentials.

Raw output: [`results/abc-cache-off-2026-11-18.txt`](results/abc-cache-off-2026-11-18.txt).

| Case      | Pass      |      p50 |      p95 |      p99 | req/s |    MB | status           |
| --------- | --------- | -------: | -------: | -------: | ----: | ----: | ---------------- |
| A wrapper | first c=1 |  2704 ms |  3472 ms |  3725 ms |   0.4 | 25.28 | 200 ×100         |
|           | warm c=1  |  2643 ms |  3441 ms |  3901 ms |   0.4 |       |                  |
|           | warm c=4  |  6309 ms |  9468 ms | 10049 ms |   0.6 |       |                  |
|           | warm c=16 | 25891 ms | 30749 ms | 38611 ms |   0.6 |       |                  |
| B martin  | first c=1 |  2652 ms |  3654 ms |  4995 ms |   0.4 | 25.28 | 200 ×100         |
|           | warm c=1  |  2576 ms |  3454 ms |  4056 ms |   0.4 |       |                  |
|           | warm c=4  |  6221 ms | 11712 ms | 14742 ms |   0.6 |       |                  |
|           | warm c=16 | 25915 ms | 31111 ms | 34053 ms |   0.6 |       |                  |
| C PMTiles | first c=1 |   213 ms |   504 ms |   807 ms |   4.3 |  8.32 | 200 ×86, 204 ×14 |
|           | warm c=1  |     2 ms |     3 ms |     4 ms | 542.5 |       |                  |
|           | warm c=4  |     4 ms |     7 ms |     9 ms | 882.6 |       |                  |
|           | warm c=16 |    17 ms |    27 ms |    30 ms | 941.3 |       |                  |

Parity: A vs B **0** tiles differ by more than 2% (max 0.8%), and both return the same 100 tiles.
A vs C is unchanged: 83 tiles differ, 14 exist only in A.

- **A ≈ B still holds.** The wrapper adds nothing measurable at any concurrency level.
- **A and B are both about 8× slower than on 2026-10-27**, and slower by the same amount. So the
  cause is under both of them: the martin/DuckDB tiler (crates.io `2.0.0-beta.7` here, against the
  local checkout used before), not fastgeoapi or PyO3. The network to Tigris isn't the cause: C's
  first pass, which reads the same bucket, is as fast as before (213 ms against 223 ms).
  Throughput is flat at 0.4–0.6 req/s from c=1 to c=16: tile queries now run nearly one at a time.
  This is worth investigating in martin before reading anything else into the A/B numbers.
- **C's warm passes are now served from memory** (p50 2–17 ms, against about 190 ms before), so
  after the first pass C no longer measures byte-range reads from Tigris. Only C's first pass is
  comparable with the earlier run.

### martin 1.16.1 vs 2.0.0-beta.7

Run on 2026-11-18 to find where the 8× slowdown comes from. Both are standalone binaries from
crates.io, built in release mode with only DuckDB support:

```shell
cargo install martin --version =1.16.1      --locked --no-default-features --features unstable-duckdb
cargo install martin --version =2.0.0-beta.7 --locked --no-default-features --features unstable-duckdb
```

1.16.1 has no object-store keys (`endpoint`, `region`, `skip_signature`,
`virtual_hosted_style_request` are ignored, and DuckDB then asks AWS S3 and gets a 404). So both
servers load [`martin-https.yaml`](martin-https.yaml), which reads the same object over public
HTTPS. Both use DuckDB's default `pool_size: 4`. The tile list and options are the same as in
step 3. Raw output:
[`results/martin-1.16.1-vs-2.0.0-beta.7-https.txt`](results/martin-1.16.1-vs-2.0.0-beta.7-https.txt).

| martin           | bundled DuckDB | Pass      |      p50 |      p95 |      p99 | req/s |
| ---------------- | -------------- | --------- | -------: | -------: | -------: | ----: |
| **1.16.1**       | 1.5.5          | first c=1 |   327 ms |  1078 ms |  1237 ms |   2.6 |
|                  |                | warm c=1  |   329 ms |   367 ms |   415 ms |   3.0 |
|                  |                | warm c=4  |   650 ms |  1397 ms |  6649 ms |   4.4 |
|                  |                | warm c=16 |  2843 ms |  3277 ms |  4029 ms |   5.5 |
| **2.0.0-beta.7** | 2.0.0          | first c=1 |  2729 ms |  3565 ms |  4385 ms |   0.4 |
|                  |                | warm c=1  |  2656 ms |  3535 ms |  3927 ms |   0.4 |
|                  |                | warm c=4  |  6345 ms | 11005 ms | 25256 ms |   0.6 |
|                  |                | warm c=16 | 25747 ms | 29998 ms | 34592 ms |   0.6 |

Parity: **0** tiles differ by more than 2% (max 0.3%), and both return the same 100 tiles.

- **The slowdown is in martin 2.0.0-beta.7.** On the same host, the same data and the same tiles,
  1.16.1 is about 8× faster at every concurrency level, and its numbers match the 2026-10-27 run
  (p50 about 325 ms at c=1, about 5.5–6 req/s at c=16).
- **It isn't the S3 access path.** Over HTTPS, beta.7 is exactly as slow as it was over the S3 API
  in the re-run above (p50 about 2.7 s).
- **The most likely cause is the DuckDB upgrade** that beta.7 brings in (`duckdb` crate 1.10505.0 →
  1.20000.1, i.e. DuckDB 1.5.5 → 2.0.0). Between these versions martin also goes from
  `martin-core` 0.11 to 0.17, so this run alone doesn't prove which change is responsible.
- Until this is fixed upstream, martin-py could pin a martin version with DuckDB 1.5.x. Its
  source config would then lose the object-store keys the `store_options` translation relies on.

### Martin tile provider, 2026-11-24

Same host, same tile list and options as step 3. What changed:

- **A** is the martin tile provider: the `lazio-roads-martin` collection, served through the OGC
  API Tiles route (`{z}/{y}/{x}`), with the martin-py **v0.1.1** release wheel (martin
  `2.0.0-beta.7`) and `cache_size_mb: 0`.
- **B** is martin `2.0.0-beta.7` from crates.io, release build, DuckDB only, loading the
  `martin.yaml` written from A's provider definition (step 1).
- fastgeoapi ran with `DEV_JWKS_ENABLED=false DEV_API_KEY_ENABLED=false DEV_OPA_ENABLED=false`.

Raw output: [`results/abc-cache-off-2026-11-24.txt`](results/abc-cache-off-2026-11-24.txt).

| Case       | Pass      |      p50 |      p95 |      p99 |  req/s |    MB | status           |
| ---------- | --------- | -------: | -------: | -------: | -----: | ----: | ---------------- |
| A provider | first c=1 |  2940 ms |  6072 ms | 13155 ms |    0.3 | 25.28 | 200 ×100         |
|            | warm c=1  |  2632 ms |  3661 ms |  4034 ms |    0.4 |       |                  |
|            | warm c=4  |  6546 ms | 10433 ms | 13529 ms |    0.6 |       |                  |
|            | warm c=16 | 27292 ms | 32500 ms | 38228 ms |    0.6 |       |                  |
| B martin   | first c=1 |  2671 ms |  3500 ms |  5380 ms |    0.4 | 25.28 | 200 ×100         |
|            | warm c=1  |  2647 ms |  3666 ms |  4838 ms |    0.4 |       |                  |
|            | warm c=4  |  6041 ms | 10333 ms | 17391 ms |    0.6 |       |                  |
|            | warm c=16 | 25780 ms | 31246 ms | 36956 ms |    0.6 |       |                  |
| C PMTiles  | first c=1 |     2 ms |     5 ms |   249 ms |  204.3 |  8.32 | 200 ×86, 204 ×14 |
|            | warm c=1  |     1 ms |     3 ms |     3 ms |  640.5 |       |                  |
|            | warm c=4  |     4 ms |     7 ms |     9 ms |  982.5 |       |                  |
|            | warm c=16 |    14 ms |    20 ms |    25 ms | 1107.9 |       |                  |

Parity: A vs B **0** tiles differ by more than 2% (max 0.3%), and both return the same 100 tiles.
A vs C is unchanged: 83 tiles differ, 14 exist only in A.

- **The provider costs about what the wrapper did.** Warm, A and B are level at c=1 (2632 against
  2647 ms) and have the same throughput at every level (0.4–0.6 req/s); at c=4 and c=16 A's p50 is
  6–8% higher. Against the wrapper's 2026-11-18 run, A's warm p50 is unchanged at c=1 (2632 against
  2643 ms) and within 6% at c=16. The OGC route, the zoom limits and the version check add
  nothing that shows next to a tile DuckDB takes seconds to cut; in-process, without the network,
  the provider answers a trivial GeoJSON tile in under 1 ms (`tests/test_martin_benchmark.py`).
- **A's first pass has a longer tail** (p99 13.2 s against 5.4 s for B). With one sample per cell
  this is a handful of slow tiles, not a trend: the readiness check had already made martin load
  the source, so A's first pass paid for no extra loading. Re-run with `--repeat 3` before reading
  anything into it.
- **martin 2.0.0-beta.7 is still the bottleneck:** A and B remain about 8× slower than the
  2026-10-27 run on the local martin checkout, and flat at 0.6 req/s from c=4 up (see
  [martin 1.16.1 vs 2.0.0-beta.7](#martin-1161-vs-200-beta7)).
- **C's first pass is no longer cold.** fastgeoapi's range cache keeps the archive's byte ranges on
  disk across restarts (`.cache/ranges/`, or `FASTGEOAPI_CACHE_DIR`), so this first pass (p50 2 ms)
  was mostly served from earlier runs' cache. It is not comparable with the 2026-10-27 first pass
  (p50 223 ms); empty that directory, or set `DEV_FASTGEOAPI_RANGE_CACHE=off`, for a cold one.

## Caveats

- The readiness check before the run fetched one z10 tile from each endpoint
  (`10/546/379`), so the "first pass" isn't a fully cold start.
- The load generator ran on the same host as the servers, which competes for the same CPU.
  For production-like numbers, run it from a separate machine, and put the servers close to
  Tigris.
- `--repeat 1` gives one sample per cell. Use `--repeat 3` or more before drawing
  conclusions from p99.
- [`results/auto-mode-cache-on.txt`](results/auto-mode-cache-on.txt) is a partial run of the former
  wrapper with martin's tile cache left on, stopped during martin's warm passes. It's kept only as
  evidence of what that cache does to the numbers (see step 1).
