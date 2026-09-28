"""Measure how many maps a fastgeoapi deployment draws per second.

Each request asks for the map of a random bbox inside the collection's extent,
at one of the given sizes. The run prints the throughput, the latency
percentiles and how many answers had each status: a 503 is the renderer's
queue refusing work, which is part of the behaviour being measured.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections import Counter

import httpx
import typer

app = typer.Typer(add_completion=False)


def summarise(latencies: list[float], statuses: list[int], elapsed: float) -> dict:
    """Throughput, latency percentiles in seconds and the count of each status."""
    ordered = sorted(latencies)

    def percentile(share: float) -> float:
        return ordered[max(0, round(share * len(ordered)) - 1)]

    return {
        "requests": len(latencies),
        "req_s": round(len(latencies) / elapsed, 2),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "statuses": {str(k): v for k, v in sorted(Counter(statuses).items())},
    }


def _bbox(extent: tuple[float, float, float, float], rng: random.Random) -> str:
    xmin, ymin, xmax, ymax = extent
    width = (xmax - xmin) * rng.uniform(0.05, 0.3)
    height = (ymax - ymin) * rng.uniform(0.05, 0.3)
    x = rng.uniform(xmin, xmax - width)
    y = rng.uniform(ymin, ymax - height)
    return f"{x},{y},{x + width},{y + height}"


@app.command()
def main(
    url: str = typer.Argument(..., help="Base URL of the deployment, e.g. https://example.fly.dev"),
    collection: str = typer.Option("lazio-roads-tiles", help="The map collection"),
    extent: str = typer.Option("11.4,41.2,14.1,42.9", help="xmin,ymin,xmax,ymax in CRS84"),
    sizes: str = typer.Option("512x512,1024x768", help="Image sizes to draw, comma separated"),
    concurrency: int = typer.Option(8, help="Maps in flight at once"),
    requests: int = typer.Option(200, help="Maps to ask for in total"),
    token: str = typer.Option(
        "", envvar="FASTGEOAPI_TOKEN", help="Bearer token, if the API needs one"
    ),
    seed: int = typer.Option(1, help="Seed of the random bboxes and sizes"),
) -> None:
    """Draw REQUESTS maps with CONCURRENCY in flight and print the summary as JSON."""
    rng = random.Random(seed)  # ruff: ignore[suspicious-non-cryptographic-random-usage]  # nosec B311
    bounds = tuple(float(v) for v in extent.split(","))
    shapes = [tuple(int(v) for v in s.split("x")) for s in sizes.split(",")]
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    latencies: list[float] = []
    statuses: list[int] = []
    pending = asyncio.Queue()
    for _ in range(requests):
        width, height = rng.choice(shapes)
        pending.put_nowait(
            {"bbox": _bbox(bounds, rng), "width": width, "height": height, "f": "png"}
        )

    async def worker(client: httpx.AsyncClient) -> None:
        while not pending.empty():
            params = pending.get_nowait()
            started = time.perf_counter()
            response = await client.get(f"{url}/collections/{collection}/map", params=params)
            latencies.append(time.perf_counter() - started)
            statuses.append(response.status_code)

    async def run() -> float:
        async with httpx.AsyncClient(headers=headers, timeout=60) as client:
            started = time.perf_counter()
            await asyncio.gather(*(worker(client) for _ in range(concurrency)))
            return time.perf_counter() - started

    elapsed = asyncio.run(run())
    typer.echo(json.dumps(summarise(latencies, statuses, elapsed), indent=2))


if __name__ == "__main__":
    app()
