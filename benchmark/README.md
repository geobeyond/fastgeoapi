# Vector tile benchmark: martin-wrapper vs martin vs pygeoapi PMTiles

This compares three ways fastgeoapi can serve the **same Lazio road segments**
as Mapbox Vector Tiles. All three run against one fixed, seeded tile list,
with the same load generator, on the same machine.

| Case                         | Endpoint                                                                         | Source                                                        | Tiles made                               |
| ---------------------------- | -------------------------------------------------------------------------------- | ------------------------------------------------------------- | ---------------------------------------- |
| **A. fastgeoapi + martin-py** | `/geoapi/martin-wrapper/transportation-lazio/{z}/{x}/{y}`                        | `s3://fastgeoapi-demo/overture/transportation-lazio.parquet`  | on request, by Martin's DuckDB tiler, in-process |
| **B. standalone `martin`**    | `/transportation-lazio/{z}/{x}/{y}`                                              | same GeoParquet, same derived config                          | on request, same tiler, no Python        |
| **C. pygeoapi PMTiles**       | `/geoapi/collections/lazio-roads-tiles/tiles/WebMercatorQuad/{z}/{y}/{x}?f=mvt` | `s3://fastgeoapi-demo/tiles/lazio-roads.pmtiles` (tippecanoe) | ahead of time; read by byte range        |

- **A vs B** isolates what the Python side costs: Starlette, the threadpool hop and the PyO3 call.
  The tiler, its config and the data are identical.
- **A/B vs C** compares generating tiles from GeoParquet when they're requested with serving
  tiles built ahead of time. The tile *content* differs (tippecanoe simplifies and drops
  features), so this is a comparison of serving strategies, not a like-for-like one.

Both objects are public and unsigned on Tigris (`t3.storage.dev`). Using one staged file of
known size, rather than a whole Overture release, keeps run-to-run variance down to the
network and the tiler.

## Files

| File                                                         | What it is                                                                          |
| ------------------------------------------------------------ | ----------------------------------------------------------------------------------- |
| [`pygeoapi-config.bench.yml`](pygeoapi-config.bench.yml)     | pygeoapi config with `lazio-roads` (GeoParquet) and `lazio-roads-tiles` (PMTiles)   |
| [`martin.yaml`](martin.yaml)                                 | Martin config derived from it (generated, see step 1); used by **both** A and B     |
| [`../scripts/bench_tiles.py`](../scripts/bench_tiles.py)     | `config`: derive `martin.yaml` · `run`: fetch the tile list from each target, report |
| [`results/`](results/)                                       | raw output of the runs below                                                        |

## Prerequisites

```shell
uv sync --extra martin_wrapper      # martin-py; build the wheel with --release
cargo build --release -p martin     # in the martin repo, for case B
```

Use release builds for both. A debug build of martin-py or martin decides the result by itself.

## 1. Derive the Martin config

```shell
uv run python scripts/bench_tiles.py config \
    --pygeoapi-config benchmark/pygeoapi-config.bench.yml \
    --resource lazio-roads \
    --output benchmark/martin.yaml
```

This produces exactly what `FASTGEOAPI_MARTIN_WRAPPER_CONFIG=auto` would derive for
`lazio-roads` (the Tigris `store_options` are translated to Martin's object-store keys). It
also adds `cache.size_mb: 0`.

`--resource lazio-roads` is needed. Without it, `auto` also turns `lazio-roads-tiles` into a
Martin `pmtiles` source, but without its Tigris endpoint, so it can't be read.

> [!IMPORTANT]
> **Don't benchmark case A with `auto`.** martin-py builds its tile manager from the config, and
> Martin's default tile cache is 512 MB. Under `auto` nothing turns it off, so after the first
> pass the wrapper answers from memory. [`results/auto-mode-cache-on.txt`](results/auto-mode-cache-on.txt)
> shows warm p50 **1 ms** for the wrapper against **324 ms** for an uncached martin. Point
> fastgeoapi at the generated file instead, so A and B run with the same cache setting.

## 2. Start the servers

Restart both servers before every run if the first pass is meant to be cold.

```shell
# A and C: one fastgeoapi process serves both
DEV_PYGEOAPI_CONFIG=benchmark/pygeoapi-config.bench.yml \
DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG=$PWD/benchmark/martin.yaml \
MARTIN_PY_POLL_DIRECTLY= RUST_LOG=warn \
uv run fastgeoapi run --host 127.0.0.1 --port 5999

# B
RUST_LOG=warn ../martin/target/release/martin \
    --config benchmark/martin.yaml --listen-addresses 127.0.0.1:3999
```

- Don't use `--reload`.
- Unset `MARTIN_PY_POLL_DIRECTLY`; it's a debugging aid for the config load.
- fastgeoapi logs `Martin wrapper endpoint mounted at /geoapi/martin-wrapper` once case A is ready.

## 3. Run

```shell
uv run python scripts/bench_tiles.py run \
  --target 'A-wrapper=http://127.0.0.1:5999/geoapi/martin-wrapper/transportation-lazio/{z}/{x}/{y}' \
  --target 'B-martin=http://127.0.0.1:3999/transportation-lazio/{z}/{x}/{y}' \
  --target 'C-pmtiles=http://127.0.0.1:5999/geoapi/collections/lazio-roads-tiles/tiles/WebMercatorQuad/{z}/{y}/{x}?f=mvt' \
  --zoom 10 --zoom 11 --zoom 12 --zoom 13 --per-zoom 25 \
  --concurrency 1 --concurrency 4 --concurrency 16 --repeat 1 \
  | tee benchmark/results/abc-cache-off.txt
```

Mind the tile order: Martin's path is `{z}/{x}/{y}`, while OGC API - Tiles uses
`{tileMatrix}/{tileRow}/{tileCol}`, which is `{z}/{y}/{x}`. The zooms stop at 13 because
that's the PMTiles archive's `maxzoom`.

For each target the script runs:

1. **one first pass** over all tiles at the first concurrency level;
2. **`--repeat` warm passes** at every concurrency level.

Every pass reports p50, p95 and p99 latency, requests per second, bytes, and HTTP status
counts. The script then checks **parity**: every target's tile sizes are compared with the
first target's.

| Option                  | Default                     | Meaning                                                           |
| ----------------------- | --------------------------- | ----------------------------------------------------------------- |
| `--bbox`                | `11.4,41.2,14.1,42.9`       | west,south,east,north; Lazio, the extent of both datasets          |
| `--zoom` (repeatable)   | 10 … 14                     | zoom levels sampled                                               |
| `--per-zoom`            | 40                          | tiles sampled at random per zoom                                  |
| `--seed`                | 42                          | same seed, same tiles, same order                                 |
| `--concurrency` (rep.)  | 1, 4, 16                    | requests in flight per warm pass                                  |
| `--repeat`              | 2                           | warm passes per concurrency level                                 |
| `--tolerance`           | 0.02                        | tile size difference still counted as on par                      |

All requests send `Accept-Encoding: identity`. The wrapper never compresses tiles,
standalone Martin would if asked, and a byte count should mean the same thing on every
target.

## Results

Run on 2026-10-27, on an AMD Ryzen 7 8845HS (16 threads, 92 GB RAM, Linux) with server and
load generator on the same host. The data stayed on Tigris. The run used 100 tiles (25 per
zoom, z10–z13, seed 42) and the DuckDB pool default of `pool_size: 4`. Raw output is in
[`results/abc-cache-off.txt`](results/abc-cache-off.txt).

| Case          | Pass      | p50      | p95      | p99      | req/s    | MB    | status         |
| ------------- | --------- | -------: | -------: | -------: | -------: | ----: | -------------- |
| A wrapper     | first c=1 |   323 ms |  1075 ms |  1423 ms |      2.6 | 25.28 | 200 ×100       |
|               | warm c=1  |   321 ms |   377 ms |   507 ms |      3.0 |       |                |
|               | warm c=4  |   637 ms |  1484 ms |  7414 ms |      4.4 |       |                |
|               | warm c=16 |  2498 ms |  2978 ms |  3346 ms |      6.1 |       |                |
| B martin      | first c=1 |   322 ms |   961 ms |  1603 ms |      2.5 | 25.28 | 200 ×100       |
|               | warm c=1  |   325 ms |   372 ms |   534 ms |      3.0 |       |                |
|               | warm c=4  |   591 ms |  1657 ms |  6894 ms |      4.7 |       |                |
|               | warm c=16 |  2673 ms |  3426 ms |  3689 ms |      5.8 |       |                |
| C PMTiles     | first c=1 |   223 ms |   670 ms |  1184 ms |      3.9 |  8.32 | 200 ×86, 204 ×14 |
|               | warm c=1  |   197 ms |   410 ms |   726 ms |      4.9 |       |                |
|               | warm c=4  |   188 ms |   560 ms |   825 ms |     17.1 |       |                |
|               | warm c=16 |   178 ms |   477 ms |   671 ms |     70.3 |       |                |

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

## Caveats

- The readiness check before the run fetched one z10 tile from each endpoint
  (`10/546/379`), so the "first pass" isn't a fully cold start.
- The load generator ran on the same host as the servers, which competes for the same CPU.
  For production-like numbers, run it from a separate machine, and put the servers close to
  Tigris.
- `--repeat 1` gives one sample per cell. Use `--repeat 3` or more before drawing
  conclusions from p99.
- [`results/auto-mode-cache-on.txt`](results/auto-mode-cache-on.txt) is a partial run, stopped
  during martin's warm passes. It's kept only as evidence of the `auto`-mode tile cache
  (see step 1).
