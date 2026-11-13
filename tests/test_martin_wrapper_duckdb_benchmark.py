"""`get_tile` benchmark for the `duckdb` (GeoParquet) source, at scale.

Three dataset sizes — 100K, 1M and 10M randomly-placed points — each its own
GeoParquet file, generated once per test session by DuckDB itself
(`app.provider.duckdb_.connect`, the same engine `test_geoparquet_provider.py`
uses to build its fixture): the `duckdb` source name in `app/tiles/martin_wrapper.py`
and Martin's own config is DuckDB-*read*, but the file on disk is GeoParquet.

Same protocol as `test_martin_wrapper_benchmark.py` (see
`tile_bench_support.py` for the shared harness): 100 warm-up requests
discarded, then 1000 timed ones, every one — warm-up and timed alike —
drawing its own random `{z}/{x}/{y}`, so nothing is ever served twice; there
is no tile cache in the wrapper to begin with, and repeating coordinates
would measure DuckDB's own query-plan cache more than the per-request path
this benchmark means to time.

Points are uniform-random over the whole globe, which is the *worst* case
for a shallow tile (every feature can land in `/0/0/0`). To keep that from
swamping the sample, each dataset's random tiles are drawn no shallower than
a size-scaled minimum zoom (`_min_zoom_for`), which keeps the busiest tile
to roughly `TARGET_FEATURES_PER_TILE` features — the zoom levels real,
non-uniformly-clustered data would already have thinned out by themselves.

A plain `COPY ... FORMAT parquet` — no sort order, no bbox metadata — makes
martin's DuckDB source scan the *entire* file on every request, since it has
nothing to prune row groups by: ~450ms/tile measured locally at 10M rows,
regardless of zoom. `_make_random_geometry_geoparquet` avoids that with a
row-group-level "spatial index": rows are written in Hilbert curve order so
each row group covers a geographically compact patch, and a `bbox` struct
column plus GeoParquet 1.1 `covering` metadata tells the DuckDB source which
row groups a tile's bbox can skip entirely. Measured locally, mean per-tile
latency drops from ~450ms to ~35ms at 10M rows and from ~170ms to ~50ms at
1M — see that function's docstring for how it's built.

Even pruned, the 10M-row case is still the slowest of the three, and this
file is more requests than routine correctness tests make. Run it explicitly
rather than folding it into a full-suite pass — `pytest -s
tests/test_martin_wrapper_duckdb_benchmark.py`, or select one size with
`-k 100k`/`-k 1m`/`-k 10m` — or exclude it with `-m "not benchmark"`, the
marker every test here carries.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from tests.tile_bench_support import run_tiles

pytest.importorskip(
    "martin_py", reason="the /martin-wrapper benchmark needs the `martin_wrapper` extra"
)

WARMUP_REQUESTS = 100
BENCHMARK_REQUESTS = 1000
MAX_ZOOM = 14
#: See the module docstring: keeps the busiest tile in a uniform-random
#: sample to roughly this many features, by raising the minimum zoom drawn
#: as the dataset grows.
TARGET_FEATURES_PER_TILE = 2_000

ROW_COUNTS = {"100k": 100_000, "1m": 1_000_000, "10m": 10_000_000}

#: DuckDB's own Parquet default (~122880 rows/group) is too coarse for
#: bbox-covering pruning to narrow much down — a smaller group makes each
#: one's bbox tight enough that a tile's viewport only overlaps a handful.
ROW_GROUP_SIZE = 8_192

#: World bounds every dataset is generated over, reused both for the
#: Hilbert sort key and the file-level `bbox` in `_COVERING_GEO_METADATA`.
_WORLD_BOUNDS_SQL = "{'min_x': -180, 'min_y': -90, 'max_x': 180, 'max_y': 90}::BOX_2D"

#: GeoParquet 1.1 `geo` metadata declaring the per-row `bbox` struct
#: `_make_random_geometry_geoparquet` writes as the `covering` DuckDB's
#: `duckdb` source uses for row-group pruning (see that function's
#: docstring). DuckDB's own Parquet writer never infers this — plain
#: `COPY ... FORMAT parquet` emits `"version": "1.0.0"` with no `covering`
#: key at all — so it has to be supplied explicitly via `KV_METADATA`.
_COVERING_GEO_METADATA = json.dumps(
    {
        "version": "1.1.0",
        "primary_column": "geom",
        "columns": {
            "geom": {
                "encoding": "WKB",
                "geometry_types": ["Point"],
                "bbox": [-180.0, -90.0, 180.0, 90.0],
                "covering": {
                    "bbox": {
                        "xmin": ["bbox", "xmin"],
                        "ymin": ["bbox", "ymin"],
                        "xmax": ["bbox", "xmax"],
                        "ymax": ["bbox", "ymax"],
                    }
                },
            }
        },
    }
)


def _min_zoom_for(n_rows: int) -> int:
    """Shallowest zoom whose tiles hold ~`TARGET_FEATURES_PER_TILE` features.

    Tile area halves in each dimension per zoom level, so a uniform
    distribution puts `n_rows / 4**z` features in the busiest tile at zoom
    `z`; solving for `z` against the target gives the floor used here.
    """
    if n_rows <= TARGET_FEATURES_PER_TILE:
        return 0
    return math.ceil(math.log(n_rows / TARGET_FEATURES_PER_TILE, 4))


def _make_random_geometry_geoparquet(con, path: Path, n_rows: int) -> None:
    """Write `n_rows` uniformly-random points to `path` as GeoParquet.

    A plain, unsorted write would leave martin's `duckdb` source scanning
    the whole file on every `get_tile` — a bbox struct column's min/max
    Parquet already tracks per row group is only useful for pruning when a
    row group actually covers a small patch of the world, which a random
    write order does not guarantee (a row group of *uniformly* random rows
    covers close to the whole globe no matter how many are in it). Two
    things together give the DuckDB source a real "spatial index" to prune
    against instead:

    - `ORDER BY ST_Hilbert(geom, ...)` writes rows in Hilbert curve order,
      so points near each other on the globe land in the same (small)
      `ROW_GROUP_SIZE`-row group rather than scattered across all of them.
    - Each row's own point is repeated into a `bbox` struct
      (`xmin=xmax=x`, `ymin=ymax=y`), and `_COVERING_GEO_METADATA` declares
      that column as the GeoParquet 1.1 `covering` — the field the `duckdb`
      source's row-group pruning is keyed on (see `sources-duckdb.md` in
      Martin's own docs: "we can use the GeoParquet 1.1 covering
      declaration... to reduce the IO necessary on large duckdb queries").

    Together, a tile request only reads the row groups whose Hilbert-sorted
    bbox actually overlaps its viewport, instead of the whole file.
    """
    kv_metadata = _COVERING_GEO_METADATA.replace("'", "''")
    con.execute(
        f"""
        COPY (
            SELECT
                id,
                value,
                geom,
                {{'xmin': ST_X(geom), 'xmax': ST_X(geom), 'ymin': ST_Y(geom), 'ymax': ST_Y(geom)}} AS bbox
            FROM (
                SELECT
                    i AS id,
                    (random() * 100)::DOUBLE AS value,
                    ST_Point(random() * 360 - 180, random() * 180 - 90) AS geom
                FROM range({n_rows}) AS t(i)
            )
            ORDER BY ST_Hilbert(geom, {_WORLD_BOUNDS_SQL})
        ) TO '{path}' (
            FORMAT parquet,
            ROW_GROUP_SIZE {ROW_GROUP_SIZE},
            KV_METADATA {{'geo': '{kv_metadata}'}}
        )
        """
    )


@pytest.fixture(scope="module")
def duckdb_dataset_100k(tmp_path_factory) -> Path:
    """A GeoParquet file of 100K random points."""
    from app.provider.duckdb_ import connect

    root = tmp_path_factory.mktemp("martin-duckdb-bench-100k")
    path = root / "100k.parquet"
    _make_random_geometry_geoparquet(connect(str(root)), path, ROW_COUNTS["100k"])
    return path


@pytest.fixture(scope="module")
def duckdb_dataset_1m(tmp_path_factory) -> Path:
    """A GeoParquet file of 1M random points."""
    from app.provider.duckdb_ import connect

    root = tmp_path_factory.mktemp("martin-duckdb-bench-1m")
    path = root / "1m.parquet"
    _make_random_geometry_geoparquet(connect(str(root)), path, ROW_COUNTS["1m"])
    return path


@pytest.fixture(scope="module")
def duckdb_dataset_10m(tmp_path_factory) -> Path:
    """A GeoParquet file of 10M random points."""
    from app.provider.duckdb_ import connect

    root = tmp_path_factory.mktemp("martin-duckdb-bench-10m")
    path = root / "10m.parquet"
    _make_random_geometry_geoparquet(connect(str(root)), path, ROW_COUNTS["10m"])
    return path


def _build_duckdb_wrapper_app(tmp_path: Path, dataset_path: Path, layer_id: str):
    from app.tiles.martin_wrapper import build_martin_wrapper_app

    config_path = tmp_path / f"martin-config-{layer_id}.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "duckdb": {
                    "sources": [
                        {
                            "geoparquet": str(dataset_path),
                            "layer_id": layer_id,
                            "geometry_column": "geom",
                            "srid": 4326,
                        }
                    ]
                }
            }
        )
    )
    return build_martin_wrapper_app(str(config_path))


def _benchmark(tmp_path: Path, dataset_path: Path, label: str, capsys) -> None:
    n_rows = ROW_COUNTS[label]
    layer_id = f"duckdb_{label}"
    sub_app = _build_duckdb_wrapper_app(tmp_path, dataset_path, layer_id)
    min_zoom = _min_zoom_for(n_rows)
    rng = random.Random(1234)  # ruff: ignore[suspicious-non-cryptographic-random-usage] - reproducible benchmark

    with TestClient(sub_app) as client:
        run_tiles(client, layer_id, rng, WARMUP_REQUESTS, min_zoom=min_zoom, max_zoom=MAX_ZOOM)
        stats = run_tiles(
            client, layer_id, rng, BENCHMARK_REQUESTS, min_zoom=min_zoom, max_zoom=MAX_ZOOM
        )

    with capsys.disabled():
        print(
            f"\n[martin-wrapper duckdb benchmark] {label} ({n_rows:,} rows, "
            f"minzoom={min_zoom}): {stats.report()}"
        )
    assert stats.count == BENCHMARK_REQUESTS


@pytest.mark.benchmark
def test_get_tile_benchmark_100k(tmp_path, duckdb_dataset_100k, capsys):
    """Warm up with 100 random tiles, then benchmark 1000 more (100K rows)."""
    _benchmark(tmp_path, duckdb_dataset_100k, "100k", capsys)


@pytest.mark.benchmark
def test_get_tile_benchmark_1m(tmp_path, duckdb_dataset_1m, capsys):
    """Warm up with 100 random tiles, then benchmark 1000 more (1M rows)."""
    _benchmark(tmp_path, duckdb_dataset_1m, "1m", capsys)


@pytest.mark.benchmark
def test_get_tile_benchmark_10m(tmp_path, duckdb_dataset_10m, capsys):
    """Warm up with 100 random tiles, then benchmark 1000 more (10M rows)."""
    _benchmark(tmp_path, duckdb_dataset_10m, "10m", capsys)
