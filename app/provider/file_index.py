"""The files of a GeoParquet dataset, each with its bbox, and the ones a request meets.

A dataset made of many files is read as a glob, and DuckDB opens the
footer of every file to filter on a bbox. An index that names each file
with its bbox lets the provider hand DuckDB only the files a request
meets. The index is a stac-geoparquet file: one row per file, the
``bbox`` struct of GeoParquet 1.1 and the ``href`` of one asset.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from app.config.logging import create_logger

logger = create_logger("app.provider.file_index")

_ASSET_NAME = re.compile(r"^[A-Za-z0-9_\-]+$")
"""Asset names reach the SQL as quoted identifiers, so only these characters pass."""


class FileIndexError(ValueError):
    """The index cannot be read, or lacks what the provider needs."""


@dataclass(frozen=True)
class FileEntry:
    """One file of a dataset.

    Attributes
    ----------
    href
        Where the file is, as a path or a URL DuckDB can read.
    bbox
        ``(xmin, ymin, xmax, ymax)`` of the file, or None when the index
        gives none; such a file is never left out.
    """

    href: str
    bbox: tuple[float, float, float, float] | None


def _resolve(href: str, base: str) -> str:
    """``href`` made absolute against the location ``base`` of the index."""
    if urlsplit(href).scheme or href.startswith("/"):
        return href
    if urlsplit(base).scheme:
        return urljoin(base, href)
    return str((Path(base).parent / href).resolve())


def _planar(bbox: dict | None) -> tuple[float, float, float, float] | None:
    """The planar corners of a 4- or 6-value bbox struct."""
    if not bbox:
        return None
    try:
        return (
            float(bbox["xmin"]),
            float(bbox["ymin"]),
            float(bbox["xmax"]),
            float(bbox["ymax"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def read_stac_geoparquet(
    location: str, *, asset: str = "data", store_options: dict | None = None
) -> list[FileEntry]:
    """Read the files named by a stac-geoparquet index.

    Parameters
    ----------
    location
        The index, as a local path or a bucket URL.
    asset
        The asset whose ``href`` names the data file of each row.
    store_options
        The storage settings of the index, as for the dataset.

    Returns
    -------
    list[FileEntry]
        One entry per row, with hrefs made absolute against the index.

    Raises
    ------
    FileIndexError
        If the asset name is not a plain name, the index has no ``id``,
        ``bbox`` or ``assets.<asset>.href``, or a row has no href.

    Notes
    -----
    The reader takes only what it uses, so an index from another producer
    reads as long as it has those columns. A file without the
    ``stac-geoparquet`` key in its Parquet metadata, and rows whose bbox
    cannot be used, are read with a warning: such rows are never left out
    of a request, so the answers stay right and only those files lose the
    pruning.
    """
    import duckdb

    from app.provider.duckdb_ import connect

    if not _ASSET_NAME.match(asset):
        raise FileIndexError(f"invalid asset name for the file index: {asset!r}")
    con = connect(location, store_options=store_options)
    keys = con.execute("SELECT key FROM parquet_kv_metadata(?)", [location]).fetchall()
    if not any(bytes(key) == b"stac-geoparquet" for (key,) in keys):
        logger.warning(f"the file index {location} does not declare stac-geoparquet metadata")
    columns = dict(
        con.execute(
            "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [location],
        ).fetchall()
    )
    for name in ("id", "bbox", "assets"):
        if name not in columns:
            raise FileIndexError(f"the file index {location} has no {name}")
    try:
        # The asset name passed `_ASSET_NAME` above, and the location is a parameter.
        rows = con.execute(
            # ruff: ignore[hardcoded-sql-expression]
            f'SELECT id, assets."{asset}".href, bbox FROM read_parquet(?)',  # nosec B608
            [location],
        ).fetchall()
    except duckdb.BinderException as error:
        # The three columns are there, so what is missing is the asset or its href.
        raise FileIndexError(f"the file index {location} has no assets.{asset}.href") from error
    entries = []
    for identifier, href, bbox in rows:
        if not href:
            raise FileIndexError(
                f"the file index {location} has no href for the row {identifier!r}"
            )
        entries.append(FileEntry(href=_resolve(href, location), bbox=_planar(bbox)))
    unbounded = sum(entry.bbox is None for entry in entries)
    if unbounded:
        logger.warning(
            f"{unbounded} of {len(entries)} files in the file index {location} have no usable bbox;"
            " every request reads them"
        )
    return entries


def _meets(entry: FileEntry, minx: float, miny: float, maxx: float, maxy: float) -> bool:
    if entry.bbox is None:
        return True
    xmin, ymin, xmax, ymax = entry.bbox
    if ymin > maxy or ymax < miny:
        return False
    if minx <= maxx:
        return xmin <= maxx and xmax >= minx
    # The request crosses the antimeridian: two ranges, east and west of it.
    return xmax >= minx or xmin <= maxx


def select_files(entries: Sequence[FileEntry], bbox: Sequence[float] | None) -> list[str]:
    """Name the files whose bbox meets ``bbox``.

    Parameters
    ----------
    entries
        The files of the dataset.
    bbox
        ``[minx, miny, maxx, maxy]`` of the request, ``minx > maxx`` when it
        crosses the antimeridian; None or empty selects every file.

    Returns
    -------
    list[str]
        The hrefs, in the order of ``entries``.
    """
    if not bbox:
        return [entry.href for entry in entries]
    minx, miny, maxx, maxy = (float(value) for value in bbox[:4])
    return [entry.href for entry in entries if _meets(entry, minx, miny, maxx, maxy)]
