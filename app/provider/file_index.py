"""The files of a GeoParquet dataset, each with its bbox, and the ones a request meets.

A dataset made of many files is read as a glob, and DuckDB opens the
footer of every file to filter on a bbox. An index that names each file
with its bbox lets the provider hand DuckDB only the files a request
meets. The index is a stac-geoparquet file: one row per file, the
``bbox`` struct of GeoParquet 1.1 and the ``href`` of one asset.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

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
    rows
        The number of rows of the file, from ``table:row_count``, or None
        when the index gives no usable count.
    """

    href: str
    bbox: tuple[float, float, float, float] | None
    rows: int | None = None


def _read_row_count(value: object) -> int | None:
    """Read a ``table:row_count`` as a count; None when it is not a whole number of rows."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def resolve_href(href: str, base: str) -> str:
    """Make ``href`` absolute against ``base``, the location of the document naming it.

    A relative href is joined to the folder of ``base``, on a bucket as on
    disk: urljoin does not know ``s3://`` and keeps it relative. A document
    read from a store names data in a store, so it cannot name a local file.

    Parameters
    ----------
    href
        The href, as the index or the item writes it.
    base
        Where the index or the item was read.

    Returns
    -------
    str
        The href as DuckDB and the store layer read it.

    Raises
    ------
    FileIndexError
        If ``base`` is remote and ``href`` names a local path or a ``file:`` URL.
    """
    remote = urlsplit(base).scheme not in ("", "file")
    target = urlsplit(href)
    local = target.scheme == "file" or (not target.scheme and href.startswith("/"))
    if remote and local:
        raise FileIndexError(f"{base} is remote and names the local file {href}")
    if target.scheme or href.startswith("/"):
        return href
    if not remote:
        return str((Path(base).parent / href).resolve())
    parts = urlsplit(base)
    key = posixpath.normpath(str(PurePosixPath(parts.path).parent / href))
    return f"{parts.scheme}://{parts.netloc}{key}"


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
    try:
        keys = con.execute("SELECT key FROM parquet_kv_metadata(?)", [location]).fetchall()
    except (duckdb.IOException, duckdb.HTTPException) as error:
        raise FileIndexError(f"the file index {location} cannot be read: {error}") from error
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
    count = '"table:row_count"' if "table:row_count" in columns else "NULL"
    try:
        # The asset name passed `_ASSET_NAME` above, `count` is one of two constants,
        # and the location is a parameter.
        rows = con.execute(
            # ruff: ignore[hardcoded-sql-expression]
            f'SELECT id, assets."{asset}".href, bbox, {count} FROM read_parquet(?)',  # nosec B608
            [location],
        ).fetchall()
    except duckdb.BinderException as error:
        # The three columns are there, so what is missing is the asset or its href.
        raise FileIndexError(f"the file index {location} has no assets.{asset}.href") from error
    entries = []
    for identifier, href, bbox, row_count in rows:
        if not href:
            raise FileIndexError(
                f"the file index {location} has no href for the row {identifier!r}"
            )
        entries.append(
            FileEntry(
                href=resolve_href(href, location),
                bbox=_planar(bbox),
                rows=_read_row_count(row_count),
            )
        )
    unbounded = sum(entry.bbox is None for entry in entries)
    if unbounded:
        logger.warning(
            f"{unbounded} of {len(entries)} files in the file index {location} have no usable bbox;"
            " every request reads them"
        )
    return entries


def _ranges(west: float, east: float) -> list[tuple[float, float]]:
    """The longitude ranges of a box; one crossing the antimeridian has two."""
    if west <= east:
        return [(west, east)]
    return [(west, 180.0), (-180.0, east)]


def _meets(entry: FileEntry, minx: float, miny: float, maxx: float, maxy: float) -> bool:
    if entry.bbox is None:
        return True
    xmin, ymin, xmax, ymax = entry.bbox
    if ymin > maxy or ymax < miny:
        return False
    # The request and the file may each cross the antimeridian (west > east).
    return any(
        file_west <= request_east and file_east >= request_west
        for file_west, file_east in _ranges(xmin, xmax)
        for request_west, request_east in _ranges(minx, maxx)
    )


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


def _read_json(location: str, store_options: dict | None) -> dict:
    """The JSON document at ``location``, read through the store layer."""
    from app.provider.storage import load_store, split_source

    base, key = split_source(location)
    try:
        return json.loads(load_store(base, store_options).get(key))
    except (OSError, ValueError) as error:
        raise FileIndexError(f"the STAC document {location} cannot be read: {error}") from error


def _etag(location: str, store_options: dict | None) -> str | None:
    from app.provider.storage import load_store, split_source

    base, key = split_source(location)
    try:
        return load_store(base, store_options).head(key).etag
    except OSError:
        return None


def read_stac_item(href: str, *, asset: str, store_options: dict | None) -> FileEntry:
    """Read the data file of one STAC item.

    Parameters
    ----------
    href
        The item document.
    asset
        The asset whose ``href`` names the data file.
    store_options
        The storage settings of the catalog.

    Returns
    -------
    FileEntry
        The data file, its href made absolute against the item.

    Raises
    ------
    FileIndexError
        If the item cannot be read or has no ``assets.<asset>.href``.
    """
    item = _read_json(href, store_options)
    data = (item.get("assets") or {}).get(asset) or {}
    if not data.get("href"):
        raise FileIndexError(f"the STAC item {href} has no assets.{asset}.href")
    bbox = item.get("bbox")
    planar = None
    if isinstance(bbox, list) and len(bbox) in (4, 6):
        half = len(bbox) // 2
        planar = _planar(
            {"xmin": bbox[0], "ymin": bbox[1], "xmax": bbox[half], "ymax": bbox[half + 1]}
        )
    properties = item.get("properties")
    count = properties.get("table:row_count") if isinstance(properties, dict) else None
    return FileEntry(
        href=resolve_href(data["href"], href), bbox=planar, rows=_read_row_count(count)
    )


def _cache_path(location: str, asset: str, cache_dir: Path | None) -> Path | None:
    from app.provider.storage.cache import digest

    if cache_dir is None:
        return None
    return cache_dir / "file-index" / f"{digest(location + asset)}.json"


def _read_cached(entry: Path | None, etag: str | None) -> list[FileEntry] | None:
    if entry is None or etag is None:
        return None
    try:
        cached = json.loads(entry.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("etag") != etag:
        return None
    # An entry written before the row counts has two values.
    return [
        FileEntry(
            href=entry[0],
            bbox=tuple(entry[1]) if entry[1] else None,
            rows=_read_row_count(entry[2]) if len(entry) > 2 else None,
        )
        for entry in cached.get("entries", [])
    ]


def _write_cached(entry: Path, etag: str, entries: Sequence[FileEntry]) -> None:
    try:
        entry.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        partial = entry.with_name(f"{entry.name}.{os.getpid()}.partial")
        partial.write_text(
            json.dumps({"etag": etag, "entries": [[e.href, e.bbox, e.rows] for e in entries]})
        )
        partial.replace(entry)
    except OSError as error:
        logger.warning(f"cannot keep the file index of {entry.name} ({error})")


def read_stac_collection(
    location: str,
    *,
    asset: str = "data",
    store_options: dict | None = None,
    cache_dir: Path | None = None,
) -> list[FileEntry]:
    """Read the data files of the items of a STAC collection.

    A collection is read one item at a time, so the result is kept under
    ``cache_dir`` and read again only when the collection's ETag changes.
    A collection or an item that cannot be read raises ``FileIndexError``.

    Parameters
    ----------
    location
        The collection document.
    asset
        The asset whose ``href`` names the data file of each item.
    store_options
        The storage settings of the catalog.
    cache_dir
        Where the index is kept between runs; None keeps nothing.

    Returns
    -------
    list[FileEntry]
        One entry per ``item`` link, in the order of the links.
    """
    entry = _cache_path(location, asset, cache_dir)
    etag = _etag(location, store_options)
    cached = _read_cached(entry, etag)
    if cached is not None:
        return cached
    collection = _read_json(location, store_options)
    items = [
        resolve_href(link["href"], location)
        for link in collection.get("links", [])
        if link.get("rel") == "item" and link.get("href")
    ]
    entries = [read_stac_item(item, asset=asset, store_options=store_options) for item in items]
    if entry is not None and etag is not None:
        _write_cached(entry, etag, entries)
    return entries


def read_file_index(
    location: str,
    *,
    asset: str = "data",
    store_options: dict | None = None,
    cache_dir: Path | None = None,
) -> list[FileEntry]:
    """Read an index of files, a stac-geoparquet file or a STAC collection.

    Parameters
    ----------
    location
        The index: a ``.parquet`` file is read as stac-geoparquet, anything
        else as a STAC collection.
    asset
        The asset whose ``href`` names the data file.
    store_options
        The storage settings of the index.
    cache_dir
        Where an index built from a collection is kept between runs.

    Returns
    -------
    list[FileEntry]
        The files of the dataset.
    """
    if urlsplit(location).path.endswith(".parquet"):
        return read_stac_geoparquet(location, asset=asset, store_options=store_options)
    return read_stac_collection(
        location, asset=asset, store_options=store_options, cache_dir=cache_dir
    )
