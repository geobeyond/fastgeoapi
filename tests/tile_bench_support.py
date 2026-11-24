"""Shared timing harness for the martin tile provider benchmarks.

Used by `test_martin_benchmark.py` (the small geojson fixture) and
`test_martin_duckdb_benchmark.py` (random-geometry GeoParquet at scale).
Both follow the same protocol: warm up on discarded requests, then time a
batch where every request draws its own random `{z}/{x}/{y}`, through the
whole OGC API Tiles route (`/collections/{id}/tiles/WebMercatorQuad/...`)
of an in-process pygeoapi sub-app.

Draws can repeat (at zoom 0 every one is `/0/0/0`), and martin keeps its own
tile cache (256 MB by default), so both benchmarks configure the provider
with `cache_size_mb: 0`: every request, repeated or not, is cut afresh.
Varying the coordinates then keeps DuckDB's query-plan cache, and not just
one lucky tile, off the measurement.
"""

from __future__ import annotations

import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

from starlette.testclient import TestClient

MVT = "application/vnd.mapbox-vector-tile"


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


def martin_client(
    data: Path, collection: str, *, layer_id: str, max_zoom: int = 14, **options
) -> TestClient:
    """An in-process pygeoapi sub-app serving `data` as `collection`, cut by martin.

    martin's tile cache is off (`cache_size_mb: 0`), so a repeated draw is
    cut again rather than answered from memory.
    """
    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
    from tests.test_tiles_async_route import _collection, _config

    provider = {
        "type": "tile",
        "name": "app.provider.martin.MartinTilesProvider",
        "data": str(data),
        "options": {
            "zoom": {"min": 0, "max": max_zoom},
            "schemes": ["WebMercatorQuad"],
            "layer_id": layer_id,
            "cache_size_mb": 0,
            **options,
        },
        "format": {"name": "pbf", "mimetype": MVT},
    }
    config = _config({collection: _collection(collection, [provider])})
    return TestClient(build_pygeoapi_subapp(config, build_openapi(config)))


def random_tile(rng: random.Random, min_zoom: int = 0, max_zoom: int = 14) -> tuple[int, int, int]:
    """A random, routing-valid `(z, x, y)` — `0 <= x, y < 2**z`."""
    z = rng.randint(min_zoom, max_zoom)
    span = max(2**z, 1)
    return z, rng.randint(0, span - 1), rng.randint(0, span - 1)


def run_tiles(
    client: TestClient,
    collection: str,
    rng: random.Random,
    count: int,
    *,
    min_zoom: int = 0,
    max_zoom: int = 14,
) -> BenchmarkStats:
    """Fire `count` randomly-chosen tile requests and time each one.

    Every call draws its own `(z, x, y)` from `rng`. A tile the data has
    nothing in answers 204, a tile with features 200; anything else fails
    the benchmark. Note the route's order: `{z}/{y}/{x}`.
    """
    latencies_ms: list[float] = []
    start = time.perf_counter()
    for _ in range(count):
        z, x, y = random_tile(rng, min_zoom, max_zoom)
        request_start = time.perf_counter()
        response = client.get(
            f"/collections/{collection}/tiles/WebMercatorQuad/{z}/{y}/{x}",
            params={"f": "mvt"},
            headers={"Accept-Encoding": "identity"},
        )
        latencies_ms.append((time.perf_counter() - request_start) * 1000)
        assert response.status_code in (200, 204), (
            f"tile {z}/{x}/{y} failed: {response.status_code} {response.text}"
        )
        if response.status_code == 200:
            assert response.headers["content-type"] == MVT
    total_seconds = time.perf_counter() - start
    return BenchmarkStats(count=count, total_seconds=total_seconds, latencies_ms=latencies_ms)
