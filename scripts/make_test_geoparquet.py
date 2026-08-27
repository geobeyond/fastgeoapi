#!/usr/bin/env python
"""Regenerate the committed GeoParquet fixture.

The fixture stands in for a file written by something that is not
DuckDB — GeoPandas, GDAL, Sedona — because those carry the geometry as
a **WKB BLOB** while DuckDB writes its own GEOMETRY type. The provider
has a branch for each, and without this file only one of them is ever
taken.

It also travels to an S3 emulator in the end-to-end test, so it is kept
small enough to upload in a fixture without anyone noticing.

    uv run python scripts/make_test_geoparquet.py

The output is committed. Regenerate it only on purpose: a test asserts
its shape, and will go red if a regeneration turns the geometry back
into DuckDB's native type.
"""

from pathlib import Path
from typing import Annotated

import duckdb
import typer
from rich.console import Console

log_console = Console(stderr=True)

app = typer.Typer(add_completion=False)

DEFAULT_TARGET = Path("tests/data/lakes.parquet")

# Four lakes, chosen so a bbox over central Italy selects some and not
# others, and so string, numeric and temporal filters all have something
# to bite on. `bbox` mirrors each geometry's envelope: it is the
# GeoParquet 1.1 covering column the provider prunes on.
ROWS = """
    SELECT * FROM (VALUES
        (1, 'Bracciano',  'it',  57, TIMESTAMP '2021-06-01 10:00:00', 12.23, 42.11),
        (2, 'Bolsena',    'it', 114, TIMESTAMP '2022-06-01 10:00:00', 11.94, 42.60),
        (3, 'Garda',      'it', 370, TIMESTAMP '2023-06-01 10:00:00', 10.70, 45.60),
        (4, 'Geneva',     'ch', 580, TIMESTAMP '2024-06-01 10:00:00',  6.55, 46.45)
    ) AS t(id, name, country, area_km2, observed_at, lon, lat)
"""


@app.command()
def generate(
    target: Annotated[
        Path,
        typer.Option("--target", "-t", help="Where to write the fixture"),
    ] = DEFAULT_TARGET,
) -> None:
    """Write the fixture with WKB geometries and a covering bbox."""
    connection = duckdb.connect()
    connection.execute("INSTALL spatial; LOAD spatial;")
    target.parent.mkdir(parents=True, exist_ok=True)
    # ST_AsWKB is what makes this file third-party shaped: the column
    # lands as BLOB, the way every other writer produces it.
    # ruff: ignore[hardcoded-sql-expression]
    connection.execute(f"""
        COPY (
            SELECT
                id, name, country, area_km2, observed_at,
                {{'xmin': lon, 'xmax': lon, 'ymin': lat, 'ymax': lat}} AS bbox,
                ST_AsWKB(ST_Point(lon, lat)) AS geometry
            FROM ({ROWS})
            ORDER BY id
        ) TO '{target}' (FORMAT parquet, COMPRESSION zstd)
    """)
    # ruff: ignore[hardcoded-sql-expression]
    counted = connection.execute(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()  # nosec B608
    rows = counted[0] if counted else 0
    log_console.log(f"wrote {target} — {rows} rows, {target.stat().st_size} bytes")


if __name__ == "__main__":
    app()
