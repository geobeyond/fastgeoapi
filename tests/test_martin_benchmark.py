"""Throughput/latency benchmark for the martin tile provider (app/provider/martin.py).

Not a correctness test — `test_martin_provider.py` covers that. This drives
tile requests through the whole OGC API Tiles route of an in-process
pygeoapi sub-app (`TestClient`, no real socket) to get a repeatable read on
what fastgeoapi adds around martin: the route, the provider, the version
check and the call into martin-py.

1. 100 warm-up requests, discarded, so the timed run doesn't pay for the
   TestClient/anyio startup cost or martin's first load of the source.
2. 1000 timed requests, from which mean/median/p95/p99 latency and an
   overall requests-per-second figure are computed and printed.

Every request targets a random `{z}/{x}/{y}` with `0 <= x, y < 2**z` against
the single-point fixture `test_martin_provider.py` uses, so most tiles come
back empty (204), but every one is a legitimate, independently cut tile
request. martin's tile cache is turned off (`cache_size_mb: 0`), so a
repeated draw (every zoom-0 one is `/0/0/0`) is cut again — see
`tile_bench_support.py`.

There is no hard latency assertion: wall-clock speed is CPU- and
load-dependent, so pinning a threshold here would make the suite flaky on
slower CI runners. The pass/fail signal is correctness (every one of the
1100 requests must resolve, not error) — the timing is reported, not graded.
Run `pytest -s tests/test_martin_benchmark.py` to see it.
"""

from __future__ import annotations

import random
import shutil

import pytest

from tests.tile_bench_support import martin_client, run_tiles

pytest.importorskip("martin_py", reason="the martin benchmark needs the `martin` extra")

from tests.test_martin_provider import FIXTURE_GEOJSON

WARMUP_REQUESTS = 100
BENCHMARK_REQUESTS = 1000
COLLECTION = "rome"
# Deep enough to exercise a realistic tile pyramid, shallow enough that
# 2**z stays a sane upper bound for random x/y at every level tried.
MAX_ZOOM = 14


@pytest.mark.benchmark
def test_martin_provider_tile_benchmark(tmp_path, capsys):
    """Warm up with 100 random tiles, then benchmark 1000 more."""
    data = tmp_path / "rome.geojson"
    shutil.copy(FIXTURE_GEOJSON, data)
    rng = random.Random(1234)  # ruff: ignore[suspicious-non-cryptographic-random-usage] - reproducible benchmark

    with martin_client(data, COLLECTION, layer_id=COLLECTION, max_zoom=MAX_ZOOM) as client:
        run_tiles(client, COLLECTION, rng, WARMUP_REQUESTS, max_zoom=MAX_ZOOM)
        stats = run_tiles(client, COLLECTION, rng, BENCHMARK_REQUESTS, max_zoom=MAX_ZOOM)

    with capsys.disabled():
        print(f"\n[martin provider benchmark] {FIXTURE_GEOJSON.name}: {stats.report()}")

    assert stats.count == BENCHMARK_REQUESTS
