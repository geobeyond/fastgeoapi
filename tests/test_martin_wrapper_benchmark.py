"""Throughput/latency benchmark for `build_martin_wrapper_app` (app/tiles/martin_wrapper.py).

Not a correctness test — `test_martin_wrapper.py` already covers that. This
drives `get_tile` requests through the sub-app's `TestClient` (in-process,
no real socket) to get a repeatable read on the wrapper's own overhead:

1. 100 warm-up requests, discarded, so the timed run doesn't pay for the
   TestClient/anyio startup cost or any lazy first-call work.
2. 1000 timed requests, from which mean/median/p95/p99 latency and an
   overall requests-per-second figure are computed and printed.

Every request targets a random `{z}/{x}/{y}` (with `0 <= x, y < 2**z`, the
only constraint martin-py's routing enforces) against the same single-point
fixture source `test_martin_wrapper.py` uses, so most tiles come back empty
of features but every one is a legitimate, independently-resolved tile
request, drawn fresh for warm-up and for the timed run alike — see
`tile_bench_support.py` for why nothing here is ever served from a cache.

There is no hard latency assertion: wall-clock speed is CPU- and
load-dependent, so pinning a threshold here would make the suite flaky on
slower CI runners. The test's pass/fail signal is correctness (every one of
the 1100 requests must resolve, not error) — the timing is reported, not
graded. Run `pytest -s tests/test_martin_wrapper_benchmark.py` to see it.
"""

from __future__ import annotations

import random

import pytest
from starlette.testclient import TestClient

from tests.test_martin_wrapper import FIXTURE_GEOJSON, _write_martin_config
from tests.tile_bench_support import run_tiles

pytest.importorskip(
    "martin_py", reason="the /martin-wrapper benchmark needs the `martin_wrapper` extra"
)

WARMUP_REQUESTS = 100
BENCHMARK_REQUESTS = 1000
SOURCE_ID = "wrapper_source"
# Deep enough to exercise a realistic tile pyramid, shallow enough that
# 2**z stays a sane upper bound for random x/y at every level tried.
MAX_ZOOM = 14


@pytest.mark.benchmark
def test_build_martin_wrapper_app_get_tile_benchmark(tmp_path, capsys):
    """Warm up with 100 random tiles, then benchmark 1000 more."""
    from app.tiles.martin_wrapper import build_martin_wrapper_app

    config_path = _write_martin_config(tmp_path, source_id=SOURCE_ID)
    sub_app = build_martin_wrapper_app(str(config_path))
    rng = random.Random(1234)  # ruff: ignore[suspicious-non-cryptographic-random-usage] - reproducible benchmark

    with TestClient(sub_app) as client:
        run_tiles(client, SOURCE_ID, rng, WARMUP_REQUESTS, max_zoom=MAX_ZOOM)
        stats = run_tiles(client, SOURCE_ID, rng, BENCHMARK_REQUESTS, max_zoom=MAX_ZOOM)

    with capsys.disabled():
        print(f"\n[martin-wrapper benchmark] {FIXTURE_GEOJSON.name}: {stats.report()}")

    assert stats.count == BENCHMARK_REQUESTS
