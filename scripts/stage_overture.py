#!/usr/bin/env python
"""Stage an Overture extract as GeoParquet in an object store.

An offline tool, not part of the runtime: it reads a window out of an
Overture release, flattens the handful of nested fields worth exposing,
and writes a GeoParquet file laid out the way the provider likes it — a
``bbox`` covering struct so row groups can be skipped, and Hilbert
ordering so a spatial window touches few of them.

Destination credentials come from the standard environment variables
(``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``, and
``AWS_ENDPOINT_URL_S3`` for Tigris) — the same ones the application
reads. Locally they live in ``.tigris.env``, which git ignores:

    set -a && source .tigris.env && set +a
"""

import os
import tempfile
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

log_console = Console(stderr=True)
err_console = Console(stderr=True, style="bold red")

app = typer.Typer(add_completion=False)

OVERTURE_BUCKET = "s3://overturemaps-us-west-2"
DEFAULT_RELEASE = "2026-08-19.0"

# Per theme, the projection that turns Overture's nested schema into flat
# columns a client can filter on. `id` and `geometry` are added by the
# query builder; everything omitted here stays out of the extract on
# purpose — `sources`, `prohibited_transitions` and friends are noise in
# a feature collection and unusable through CQL2 anyway.
PROJECTIONS = {
    "places": [
        'names."primary" AS name',
        'categories."primary" AS category',
        "confidence",
        "operating_status",
        "basic_category",
    ],
    "transportation": [
        'names."primary" AS name',
        "subtype",
        "class",
        "subclass",
    ],
}


def build_sql(source: str, projection: list[str], bbox: tuple[float, ...]) -> str:
    """The extraction query: window, flatten, add a covering, order."""
    minx, miny, maxx, maxy = bbox
    columns = ",\n        ".join(["id", *projection])
    # The covering struct mirrors each geometry's envelope. Overture
    # publishes one under this name and the provider looks for it, so the
    # extract keeps the same contract.
    covering = (
        "{"
        "'xmin': ST_XMin(geometry), 'xmax': ST_XMax(geometry), "
        "'ymin': ST_YMin(geometry), 'ymax': ST_YMax(geometry)"
        "} AS bbox"
    )
    # `src` is not decoration: the projection produces a column also named
    # `bbox`, and DuckDB resolves SELECT aliases inside WHERE. Unqualified,
    # the filter could bind to the computed struct instead of the stored
    # one — same answer, but no row-group statistics and so no pruning.
    #
    # The interpolated values are the caller's own arguments — a release
    # name, a theme and four floats parsed as floats — in an offline tool
    # that never sees a request.
    # ruff: ignore[hardcoded-sql-expression]
    return f"""
    SELECT
        {columns},
        {covering},
        geometry
    FROM read_parquet('{source}', hive_partitioning = true) AS src
    WHERE src.bbox.xmin <= {maxx} AND src.bbox.xmax >= {minx}
      AND src.bbox.ymin <= {maxy} AND src.bbox.ymax >= {miny}
    ORDER BY ST_Hilbert(
        src.geometry,
        {{'min_x': {minx}, 'min_y': {miny}, 'max_x': {maxx}, 'max_y': {maxy}}}::BOX_2D
    )
    """


@app.command()
def stage(
    theme: Annotated[
        str,
        typer.Option("--theme", "-t", help=f"Overture theme: {', '.join(sorted(PROJECTIONS))}"),
    ],
    type_: Annotated[
        str,
        typer.Option("--type", help="Overture type within the theme, e.g. segment"),
    ],
    bbox: Annotated[
        str,
        typer.Option("--bbox", "-b", help="minx,miny,maxx,maxy in CRS84"),
    ],
    dest: Annotated[
        str,
        typer.Option("--dest", "-d", help="Destination URL or path for the extract"),
    ],
    release: Annotated[
        str,
        typer.Option("--release", "-r", help="Overture release to read"),
    ] = DEFAULT_RELEASE,
    local: Annotated[
        str,
        typer.Option(
            "--local",
            "-l",
            help="Keep the extract here; an existing file is uploaded as is",
        ),
    ] = "",
) -> None:
    r"""Extract an Overture window and upload it as GeoParquet.

    Examples
    --------
        uv run python scripts/stage_overture.py --theme transportation \\
            --type segment --bbox 11.4,41.2,14.1,42.9 \\
            --dest s3://fastgeoapi-demo/overture/transportation-lazio.parquet
    """
    import duckdb

    if theme not in PROJECTIONS:
        err_console.print(f"unknown theme '{theme}': pick one of {', '.join(sorted(PROJECTIONS))}")
        raise typer.Exit(code=2)

    window = tuple(float(value) for value in bbox.split(","))
    if len(window) != 4:
        err_console.print("--bbox wants four comma-separated numbers")
        raise typer.Exit(code=2)

    if dest.startswith(("s3://", "gs://", "az://")) and not os.environ.get("AWS_ACCESS_KEY_ID"):
        err_console.print("no AWS_ACCESS_KEY_ID in the environment for the destination")
        raise typer.Exit(code=2)

    source = f"{OVERTURE_BUCKET}/release/{release}/theme={theme}/type={type_}/*"

    connection = duckdb.connect()
    connection.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    # Overture's bucket is public: sign nothing, or S3 refuses the read.
    # The empty key is what stops the signing — omitting the keys instead
    # lets DuckDB pick up the destination store's credentials from the
    # environment and sign with those, which earns a 403. The scope keeps
    # this secret away from any other bucket.
    connection.execute(
        "CREATE OR REPLACE SECRET overture (TYPE s3, REGION 'us-west-2', "
        f"KEY_ID '', SECRET '', SCOPE '{OVERTURE_BUCKET}');"
    )

    # The extract is kept on disk rather than living inside a temporary
    # directory: reading a window out of Overture costs minutes, and a
    # failed upload should not throw that away. Re-running with the same
    # `--local` uploads what is already there.
    target = Path(local) if local else Path(tempfile.gettempdir()) / f"{theme}-{type_}.parquet"
    if target.exists():
        log_console.log(f"reusing the extract at {target}")
    else:
        log_console.log(f"reading {source}")
        started = time.monotonic()
        connection.execute(
            f"COPY ({build_sql(source, PROJECTIONS[theme], window)}) TO '{target}' "
            "(FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 50000)"
        )
        elapsed = time.monotonic() - started
        # Offline tool: the path is one this process just wrote.
        # ruff: ignore[hardcoded-sql-expression]
        counted = connection.execute(f"SELECT count(*) FROM read_parquet('{target}')").fetchone()
        rows = counted[0] if counted else 0
        log_console.log(
            f"extracted {rows} rows, {target.stat().st_size / 1e6:.1f} MB, in {elapsed:.1f}s"
        )

    upload(target, dest)
    log_console.log(f"uploaded to {dest}, extract kept at {target}")


def upload(source: Path, dest: str) -> None:
    """Send the extract to its destination.

    Not through the storage protocol: that one moves whole byte strings,
    which suits a configuration document and not a dataset. ``obstore``
    takes a file handle and splits it into concurrent parts, and the
    upload of a few hundred megabytes needs a client timeout to match.
    """
    import obstore
    from obstore.store import from_url

    from app.provider.storage.factory import split_source

    base, key = split_source(dest)
    store = from_url(base, client_options={"timeout": "600s"})
    with source.open("rb") as handle:
        obstore.put(store, key, handle, use_multipart=True)


if __name__ == "__main__":
    app()
