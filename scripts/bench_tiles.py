r"""Benchmark vector tile endpoints on one fixed, seeded tile list.

The sources come from ``pygeoapi-config.yml``: today the ``lazio-roads``
collection, Overture transportation segments for Lazio staged on Tigris
as a single Hilbert-ordered GeoParquet with a ``bbox`` covering
(``s3://fastgeoapi-demo/overture/transportation-lazio.parquet``). One
object of known size, rather than a whole Overture release, keeps run to
run variance down to the network and the tiler.

First derive the Martin config for the standalone ``martin`` binary from
the same pygeoapi config, so it reads exactly what fastgeoapi's
``FASTGEOAPI_MARTIN_WRAPPER_CONFIG=auto`` derives at boot (plus
``cache.size_mb: 0``: martin-py keeps no tile cache, so neither may the
binary):

    uv run python scripts/bench_tiles.py config --output benchmark/martin.yaml

Then start both servers (each freshly, if the first pass is to be cold)
and run the same tiles against both:

    DEV_FASTGEOAPI_MARTIN_WRAPPER_CONFIG=auto uv run fastgeoapi run --port 5000
    martin --config benchmark/martin.yaml --listen-addresses 0.0.0.0:3000

    uv run python scripts/bench_tiles.py run \\
        --target 'wrapper=http://localhost:5000/geoapi/martin-wrapper/transportation-lazio/{z}/{x}/{y}' \\
        --target 'martin=http://localhost:3000/transportation-lazio/{z}/{x}/{y}' \\
        --concurrency 1 --concurrency 4 --concurrency 16

The source id is ``transportation-lazio``: martin names a GeoParquet
source after its file, not after the pygeoapi resource.
"""

from __future__ import annotations

import asyncio
import math
import random
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import typer
import yaml

app = typer.Typer(add_completion=False)

LAZIO_BBOX = "11.4,41.2,14.1,42.9"


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


def sample_tiles(
    bbox: str, zooms: list[int], per_zoom: int, seed: int
) -> list[tuple[int, int, int]]:
    """At most `per_zoom` tiles of each zoom, shuffled, the same for every seed."""
    west, south, east, north = (float(v) for v in bbox.split(","))
    rng = random.Random(seed)
    tiles: list[tuple[int, int, int]] = []
    for zoom in zooms:
        candidates = tiles_in_bbox(zoom, west, south, east, north)
        tiles += rng.sample(candidates, min(per_zoom, len(candidates)))
    rng.shuffle(tiles)
    return tiles


@dataclass
class Pass:
    """What one pass over the tile list cost one target."""

    latencies: list[float] = field(default_factory=list)
    statuses: dict[int, int] = field(default_factory=dict)
    errors: int = 0
    bytes: int = 0
    wall: float = 0.0
    sizes: dict[tuple[int, int, int], int] = field(default_factory=dict)


async def run_pass(
    client: httpx.AsyncClient,
    template: str,
    tiles: list[tuple[int, int, int]],
    concurrency: int,
) -> Pass:
    """Fetch every tile once, at most `concurrency` in flight."""
    result = Pass()
    gate = asyncio.Semaphore(concurrency)

    async def one(tile: tuple[int, int, int]) -> None:
        z, x, y = tile
        async with gate:
            t0 = time.perf_counter()
            try:
                response = await client.get(template.format(z=z, x=x, y=y))
            except httpx.HTTPError:
                result.errors += 1
                return
            result.latencies.append(time.perf_counter() - t0)
        result.statuses[response.status_code] = result.statuses.get(response.status_code, 0) + 1
        if response.status_code == 200:
            result.bytes += len(response.content)
            result.sizes[tile] = len(response.content)

    started = time.perf_counter()
    await asyncio.gather(*(one(tile) for tile in tiles))
    result.wall = time.perf_counter() - started
    return result


def _report(label: str, result: Pass) -> None:
    lat = sorted(result.latencies)
    if len(lat) >= 2:
        cuts = statistics.quantiles(lat, n=100)
        p50, p95, p99 = cuts[49], cuts[94], cuts[98]
    else:
        p50 = p95 = p99 = lat[0] if lat else float("nan")
    statuses = " ".join(f"{code}:{n}" for code, n in sorted(result.statuses.items()))
    typer.echo(
        f"{label:<26} p50 {p50 * 1000:>7.0f} ms  p95 {p95 * 1000:>7.0f} ms  "
        f"p99 {p99 * 1000:>7.0f} ms | {len(lat) / result.wall:>6.1f} req/s | "
        f"{result.bytes / 1e6:>7.2f} MB | {statuses} errors:{result.errors}"
    )


@app.command()
def config(
    pygeoapi_config: Path = typer.Option(
        Path("pygeoapi-config.yml"), help="The pygeoapi config fastgeoapi boots with."
    ),
    resource: str | None = typer.Option(
        None, help="Only this resource (default: every one `auto` would mount)."
    ),
    output: Path = typer.Option(Path("benchmark/martin.yaml"), help="Where to write it."),
) -> None:
    """Write the Martin config `auto` mode derives, tile cache off."""
    # Here, not at the top: importing `app` turns on its DEBUG logging,
    # which would bury `run`'s report under httpx's request traces.
    from app.tiles.martin_wrapper import _martin_config_from_pygeoapi

    document = yaml.safe_load(pygeoapi_config.read_text())
    resources = document.get("resources") or {}
    if resource is not None:
        if resource not in resources:
            raise typer.BadParameter(f"no resource {resource!r} in {pygeoapi_config}")
        resources = {resource: resources[resource]}
    martin_config = _martin_config_from_pygeoapi({"resources": resources})
    if not martin_config:
        raise typer.BadParameter(f"martin-py has no source kind for any of {list(resources)}")
    martin_config["cache"] = {"size_mb": 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(martin_config, sort_keys=False))
    typer.echo(f"wrote {output}")


@app.command()
def run(
    target: list[str] = typer.Option(
        ..., help="name=URL template with {z}, {x} and {y}; repeat for each server."
    ),
    bbox: str = typer.Option(LAZIO_BBOX, help="west,south,east,north in degrees (default: Lazio)."),
    zoom: list[int] = typer.Option([10, 11, 12, 13, 14], help="Zoom levels to sample."),
    per_zoom: int = typer.Option(40, help="Tiles sampled per zoom level."),
    seed: int = typer.Option(42, help="Sampling seed: same seed, same tiles."),
    concurrency: list[int] = typer.Option([1, 4, 16], help="In-flight requests per warm pass."),
    repeat: int = typer.Option(2, help="Warm passes per concurrency level."),
    timeout: float = typer.Option(120.0, help="Per-request timeout in seconds."),
    tolerance: float = typer.Option(0.02, help="Relative tile size difference still on par."),
) -> None:
    """Fetch the same tiles from every target: one first pass, then warm passes."""
    targets = dict(spec.split("=", 1) for spec in target)
    tiles = sample_tiles(bbox, zoom, per_zoom, seed)
    typer.echo(f"{len(tiles)} tiles, zooms {zoom}, bbox {bbox}, seed {seed}\n")

    async def bench() -> dict[str, Pass]:
        firsts: dict[str, Pass] = {}
        for name, template in targets.items():
            # identity: the wrapper never compresses, the binary would if asked.
            headers = {"Accept-Encoding": "identity"}
            limits = httpx.Limits(max_connections=max(concurrency))
            async with httpx.AsyncClient(headers=headers, limits=limits, timeout=timeout) as client:
                typer.echo(f"[{name}] {template}")
                firsts[name] = await run_pass(client, template, tiles, concurrency[0])
                _report(f"  first pass, c={concurrency[0]}", firsts[name])
                for level in concurrency:
                    for i in range(repeat):
                        _report(
                            f"  warm c={level} #{i + 1}",
                            await run_pass(client, template, tiles, level),
                        )
            typer.echo()
        return firsts

    firsts = asyncio.run(bench())

    # Same tiles out of the same data should be about the same size. Not
    # exactly: DuckDB's parallel scan returns features in no fixed order,
    # which shifts the encoded size a little even between two requests to
    # one server.
    names = list(firsts)
    for other in names[1:]:
        reference, candidate = firsts[names[0]].sizes, firsts[other].sizes
        drifts = [
            abs(reference[t] - candidate[t]) / reference[t]
            for t in reference.keys() & candidate.keys()
        ]
        mismatched = sum(1 for drift in drifts if drift > tolerance)
        missing = reference.keys() ^ candidate.keys()
        typer.echo(
            f"parity {names[0]} vs {other}: {mismatched} tiles differ by more than "
            f"{tolerance:.0%} (max {max(drifts, default=0):.1%}), "
            f"{len(missing)} tiles found by only one"
        )


if __name__ == "__main__":
    app()
