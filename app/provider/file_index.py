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
        If the asset name is not a plain name, or the index has no
        ``bbox`` column or no ``assets.<asset>.href``.
    """
    import duckdb

    from app.provider.duckdb_ import connect

    if not _ASSET_NAME.match(asset):
        raise FileIndexError(f"invalid asset name for the file index: {asset!r}")
    con = connect(location, store_options=store_options)
    try:
        # The asset name passed `_ASSET_NAME` above, and the location is a parameter.
        rows = con.execute(
            # ruff: ignore[hardcoded-sql-expression]
            f'SELECT assets."{asset}".href, bbox FROM read_parquet(?)',  # nosec B608
            [location],
        ).fetchall()
    except duckdb.BinderException as error:
        missing = "bbox" if "bbox" in str(error) else f"assets.{asset}.href"
        raise FileIndexError(f"the file index {location} has no {missing}") from error
    return [FileEntry(href=_resolve(href, location), bbox=_planar(bbox)) for href, bbox in rows]


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
