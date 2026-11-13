"""Shared timing harness for `/martin-wrapper` `get_tile` benchmarks.

Used by `test_martin_wrapper_benchmark.py` (the small geojson fixture) and
`test_martin_wrapper_duckdb_benchmark.py` (random-geometry GeoParquet at
scale). Both follow the same protocol: warm up on discarded requests, then
time a distinct batch — every request targets its own random `{z}/{x}/{y}`,
so nothing after warm-up repeats a tile a cache could have memoized. The
wrapper itself caches nothing (`app/tiles/martin_wrapper.py` builds the
`TileServer` once and calls `get_tile` fresh every request); varying the
coordinates is what keeps DuckDB/martin-py's own query-plan caches, and not
just one lucky response, off the measurement.
"""

from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass

from starlette.testclient import TestClient


@dataclass(frozen=True)
class BenchmarkStats:
    count: int
    total_seconds: float
    latencies_ms: list[float]

    @property
    def requests_per_second(self) -> float:
        return self.count / self.total_seconds if self.total_seconds else float("inf")

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.latencies_ms)

    @property
    def median_ms(self) -> float:
        return statistics.median(self.latencies_ms)

    @property
    def p95_ms(self) -> float:
        return statistics.quantiles(self.latencies_ms, n=100)[94]

    @property
    def p99_ms(self) -> float:
        return statistics.quantiles(self.latencies_ms, n=100)[98]

    def report(self) -> str:
        return (
            f"{self.count} requests in {self.total_seconds:.3f}s "
            f"({self.requests_per_second:.1f} req/s) — "
            f"latency mean={self.mean_ms:.3f}ms median={self.median_ms:.3f}ms "
            f"p95={self.p95_ms:.3f}ms p99={self.p99_ms:.3f}ms "
            f"min={min(self.latencies_ms):.3f}ms max={max(self.latencies_ms):.3f}ms"
        )


def random_tile(rng: random.Random, min_zoom: int = 0, max_zoom: int = 14) -> tuple[int, int, int]:
    """A random, routing-valid `(z, x, y)` — `0 <= x, y < 2**z`."""
    z = rng.randint(min_zoom, max_zoom)
    span = max(2**z, 1)
    return z, rng.randint(0, span - 1), rng.randint(0, span - 1)


def run_tiles(
    client: TestClient,
    source_id: str,
    rng: random.Random,
    count: int,
    *,
    min_zoom: int = 0,
    max_zoom: int = 14,
) -> BenchmarkStats:
    """Fire `count` distinct, randomly-chosen tile requests and time each one.

    Every call draws its own `(z, x, y)` from `rng`, so a warm-up batch
    followed by the timed one never repeats a tile — nothing in the
    measured run is a memoized response rather than a freshly resolved one.
    """
    latencies_ms: list[float] = []
    start = time.perf_counter()
    for _ in range(count):
        z, x, y = random_tile(rng, min_zoom, max_zoom)
        request_start = time.perf_counter()
        response = client.get(f"/{source_id}/{z}/{x}/{y}")
        latencies_ms.append((time.perf_counter() - request_start) * 1000)
        assert response.status_code == 200, (
            f"tile {z}/{x}/{y} failed: {response.status_code} {response.text}"
        )
        assert response.headers["content-type"] == "application/x-protobuf"
    total_seconds = time.perf_counter() - start
    return BenchmarkStats(count=count, total_seconds=total_seconds, latencies_ms=latencies_ms)
