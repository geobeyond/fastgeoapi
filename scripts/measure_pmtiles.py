r"""Measure the two chains on a real PMTiles archive (ADR-0011, the measurement).

The same tiles are fetched twice from a fresh provider: once through the
synchronous face in a threadpool the size of pygeoapi's default
executor, once through the awaited face gathered on one event loop. The
byte ranges are wrapped to count reads and bytes, so the numbers say
what a map view costs, not just how long it takes.

    uv run python scripts/measure_pmtiles.py \\
        s3://overturemaps-extras-us-west-2/tiles/2026-08-19.0/divisions.pmtiles \\
        --region us-west-2 --skip-signature --zoom 8 --count 50
"""

from __future__ import annotations

import asyncio
import math
import statistics
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

import typer

from app.provider.pmtiles import PMTilesProvider
from app.provider.storage import SingleFlightRanges

app = typer.Typer(add_completion=False)


class CountingRanges:
    """A ByteRanges wrapper that counts requests and bytes across threads."""

    def __init__(self, inner):
        self._inner = inner
        self._lock = threading.Lock()
        self.reads = 0
        self.bytes = 0

    def _note(self, length: int) -> None:
        with self._lock:
            self.reads += 1
            self.bytes += length

    def read(self, offset: int, length: int) -> bytes:
        """Count, then read."""
        self._note(length)
        return self._inner.read(offset, length)

    async def aread(self, offset: int, length: int) -> bytes:
        """Count, then await the read."""
        self._note(length)
        return await self._inner.aread(offset, length)

    def read_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Count every range, then read them."""
        for _, length in ranges:
            self._note(length)
        return self._inner.read_many(ranges)

    async def aread_many(self, ranges: Sequence[tuple[int, int]]) -> list[bytes]:
        """Count every range, then await them."""
        for _, length in ranges:
            self._note(length)
        return await self._inner.aread_many(ranges)


def tiles_in_bbox(
    zoom: int, west: float, south: float, east: float, north: float
) -> list[tuple[int, int, int]]:
    """Every WebMercatorQuad tile at `zoom` touching the bbox, row by row."""

    def column(lon: float) -> int:
        return int((lon + 180.0) / 360.0 * 2**zoom)

    def row(lat: float) -> int:
        rad = math.radians(lat)
        return int((1.0 - math.log(math.tan(rad) + 1.0 / math.cos(rad)) / math.pi) / 2.0 * 2**zoom)

    return [
        (zoom, x, y)
        for y in range(row(north), row(south) + 1)
        for x in range(column(west), column(east) + 1)
    ]


def _fresh(provider_def: dict) -> PMTilesProvider:
    provider = PMTilesProvider(provider_def)
    # Count below the single-flight layer: what actually reaches the store.
    counting = CountingRanges(provider.ranges.inner)
    provider.ranges = SingleFlightRanges(counting)
    provider.counting = counting
    return provider


def _report(
    label: str, latencies: list[float], wall: float, provider: PMTilesProvider, found: int
) -> None:
    ranges = provider.counting
    p50, p95 = statistics.quantiles(latencies, n=20)[9], statistics.quantiles(latencies, n=20)[18]
    typer.echo(
        f"{label:<28} tiles {len(latencies):>3} (found {found:>3}) | "
        f"p50 {p50 * 1000:>6.0f} ms  p95 {p95 * 1000:>6.0f} ms | "
        f"wall {wall:>6.2f} s | range reads {ranges.reads:>4} | {ranges.bytes / 1e6:>6.2f} MB"
    )


@app.command()
def main(
    data: str = typer.Argument(..., help="The archive: a path, or an s3://, gs://, az:// URL."),
    zoom: int = typer.Option(8, help="Zoom level of the tiles to fetch."),
    bbox: str = typer.Option(
        "6.6,36.6,18.5,47.1", help="west,south,east,north in degrees (default: Italy)."
    ),
    count: int = typer.Option(50, help="How many tiles of the bbox to fetch."),
    workers: int = typer.Option(
        5, help="Threadpool size for the synchronous chain (pygeoapi's default on 1 vCPU)."
    ),
    region: str | None = typer.Option(None, help="Bucket region."),
    endpoint: str | None = typer.Option(None, help="S3-compatible endpoint, host[:port]."),
    skip_signature: bool = typer.Option(False, help="Public bucket: no credentials."),
) -> None:
    """Fetch the same tiles through both faces of the provider and print what each costs."""
    store_options = {
        key: value
        for key, value in (
            ("region", region),
            ("endpoint", endpoint),
            ("skip_signature", skip_signature or None),
        )
        if value is not None
    }
    provider_def = {
        "type": "tile",
        "name": "app.provider.pmtiles.PMTilesProvider",
        "data": data,
        "store_options": store_options,
        "options": {"zoom": {"min": 0, "max": 22}, "schemes": ["WebMercatorQuad"]},
        "format": {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"},
    }
    west, south, east, north = (float(v) for v in bbox.split(","))
    tiles = tiles_in_bbox(zoom, west, south, east, north)[:count]
    typer.echo(f"{data}\n{len(tiles)} tiles at zoom {zoom} in bbox {bbox}\n")

    # First request: header, root and metadata, once per instance.
    warm = _fresh(provider_def)
    started = time.perf_counter()
    warm.get_tiles(z=tiles[0][0], y=tiles[0][2], x=tiles[0][1], format_="pbf")
    typer.echo(
        f"{'first request (open + tile)':<28} {(time.perf_counter() - started) * 1000:>6.0f} ms | "
        f"range reads {warm.counting.reads} | {warm.counting.bytes / 1e3:.1f} KB\n"
    )

    # (a) The synchronous face in a threadpool: pygeoapi's chain.
    provider = _fresh(provider_def)
    latencies: list[float] = []
    found = 0

    def one_sync(tile: tuple[int, int, int]) -> None:
        nonlocal found
        z, x, y = tile
        t0 = time.perf_counter()
        if provider.get_tiles(z=z, y=y, x=x, format_="pbf") is not None:
            found += 1
        latencies.append(time.perf_counter() - t0)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one_sync, tiles))
    _report(f"sync, {workers} threads", latencies, time.perf_counter() - started, provider, found)

    # (b) The awaited face, all tiles in flight together: fastgeoapi's chain.
    provider = _fresh(provider_def)

    async def one_async(tile: tuple[int, int, int]) -> tuple[float, bool]:
        z, x, y = tile
        t0 = time.perf_counter()
        tile_bytes = await provider.aget_tiles("layer", "WebMercatorQuad", z, y, x, "pbf")
        return time.perf_counter() - t0, tile_bytes is not None

    async def gathered() -> tuple[list[tuple[float, bool]], float]:
        t0 = time.perf_counter()
        results = await asyncio.gather(*(one_async(tile) for tile in tiles))
        return list(results), time.perf_counter() - t0

    results, wall = asyncio.run(gathered())
    _report(
        "async, gathered",
        [lat for lat, _ in results],
        wall,
        provider,
        sum(1 for _, ok in results if ok),
    )


if __name__ == "__main__":
    app()
