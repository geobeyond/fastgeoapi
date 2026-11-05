"""An id index the data publisher ships, and the lookup of one id in it.

A dataset of many files gives no way to tell which file holds an id, so a
lookup by id reads the id column of every file. A publisher can ship an
index of its ids, one row per feature with the file that holds it, sorted
by id across a few Parquet files; an example of this mechanism is the
GERS registry of Overture. The range of ids of each index file comes from
its footer, so a lookup opens only the file whose range holds the id,
and a row group of it.
"""

from __future__ import annotations

import fnmatch
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.logging import create_logger

logger = create_logger("app.provider.id_index")

_TEXT_TYPES = ("VARCHAR", "UUID")
_NUMBER_TYPES = (
    *("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT"),
    *("UTINYINT", "USMALLINT", "UINTEGER", "UBIGINT", "UHUGEINT"),
    *("FLOAT", "DOUBLE", "DECIMAL"),
)


class IdIndexError(ValueError):
    """The id index is malformed, cannot be read, or lacks a column it names."""


@dataclass(frozen=True)
class RetrievedIdIndex:
    """An id index shipped by the data publisher.

    Attributes
    ----------
    location
        The index: a Parquet file, or a glob of Parquet files, on disk or in
        a bucket.
    id_column
        The column with the id of each feature.
    href_column
        The column with the href of the file that holds the feature, or None
        when the index gives a path relative to ``href_base``.
    path_column
        The column with that path, or None when the index gives hrefs.
    bbox_column
        The column with the bbox of each feature, a struct of ``xmin``,
        ``ymin``, ``xmax`` and ``ymax``, or None.
    href_base
        What a path is joined to, for an index that gives paths.
    """

    location: str
    id_column: str
    href_column: str | None
    path_column: str | None
    bbox_column: str | None
    href_base: str | None

    @classmethod
    def from_definition(cls, definition: Mapping[str, Any]) -> RetrievedIdIndex | None:
        """Read the ``id_index`` mapping of a provider.

        Parameters
        ----------
        definition
            The mapping, with ``type``, ``location``, ``columns`` and, for an
            index that gives paths, ``href_base``.

        Returns
        -------
        RetrievedIdIndex | None
            The index, or None for an index of ``type: generated``, which
            this version does not read.

        Raises
        ------
        IdIndexError
            If the mapping lacks a key the index needs, or names an unknown
            type.
        """
        kind = definition.get("type")
        if kind == "generated":
            logger.warning("an id_index of type generated is not read yet; get reads every file")
            return None
        if kind != "retrieved":
            raise IdIndexError(f"unknown id_index type: {kind!r}")
        location = definition.get("location")
        columns = definition.get("columns")
        if not isinstance(location, str) or not location or not isinstance(columns, Mapping):
            raise IdIndexError("an id_index needs a location and columns")
        id_column = columns.get("id")
        href_column = columns.get("href")
        path_column = columns.get("path")
        if not id_column or not (href_column or path_column):
            raise IdIndexError("the columns of an id_index name the id and an href or a path")
        href_base = definition.get("href_base")
        if path_column and not href_base:
            raise IdIndexError("an id_index that gives paths needs href_base")
        return cls(
            location=location,
            id_column=str(id_column),
            href_column=str(href_column) if href_column else None,
            path_column=str(path_column) if path_column else None,
            bbox_column=str(columns["bbox"]) if columns.get("bbox") else None,
            href_base=str(href_base) if href_base else None,
        )


@dataclass(frozen=True)
class IdRow:
    """The row of an id in the index.

    Attributes
    ----------
    href
        The file that holds the feature, or None when the row names none.
    bbox
        ``(xmin, ymin, xmax, ymax)`` of the feature, or None.
    """

    href: str | None
    bbox: tuple[float, float, float, float] | None


def _list_files(location: str, store_options: dict | None) -> list[tuple[str, str | None]]:
    """List the files of the index with their ETags, in href order."""
    from app.provider.storage import load_store, split_source

    base, pattern = split_source(location)
    try:
        entries = load_store(base, store_options).entries("")
    except OSError as error:
        raise IdIndexError(f"the id index {location} cannot be listed: {error}") from error
    files = [
        (f"{base.rstrip('/')}/{entry.path}", entry.etag)
        for entry in entries
        if fnmatch.fnmatch(entry.path, pattern)
    ]
    if not files:
        raise IdIndexError(f"the id index {location} names no file")
    return sorted(files)


def _read_range(
    href: str, column: str, store_options: dict | None
) -> tuple[str, str | None, str | None]:
    """Read the type and the smallest and largest id of one index file from its footer.

    A row group without statistics leaves both bounds None: the file may hold any id.
    """
    from app.provider.duckdb_ import connect

    con = connect(href, store_options=store_options)
    types = dict(
        con.execute(
            "SELECT column_name, column_type FROM (DESCRIBE SELECT * FROM read_parquet(?))",
            [href],
        ).fetchall()
    )
    if column not in types:
        raise IdIndexError(f"the id index file {href} has no column {column}")
    low, high, unbounded = con.execute(
        "SELECT min(stats_min_value), max(stats_max_value),"
        " count(*) FILTER (WHERE stats_min_value IS NULL OR stats_max_value IS NULL)"
        " FROM parquet_metadata(?) WHERE path_in_schema = ?",
        [href, column],
    ).fetchone()
    if unbounded or low is None or high is None:
        return str(types[column]), None, None
    return str(types[column]), str(low), str(high)


def _read_ranges(
    index: RetrievedIdIndex, store_options: dict | None, cache_dir: Path | None
) -> list[tuple[str, str, str | None, str | None]]:
    """The ``(href, type, smallest id, largest id)`` of each file of the index.

    The ranges are kept under ``cache_dir`` with the ETag of each file, and
    read again only when one listing of the index names other files or ETags.
    """
    from app.provider.storage.cache import digest

    files = _list_files(index.location, store_options)
    entry = cache_dir / "id-index" / f"{digest(index.location)}.json" if cache_dir else None
    if entry is not None:
        try:
            cached = json.loads(entry.read_text())
        except (OSError, ValueError):
            cached = None
        if isinstance(cached, dict) and cached.get("files") == [list(f) for f in files]:
            return [tuple(row) for row in cached["ranges"]]
    ranges = [(href, *_read_range(href, index.id_column, store_options)) for href, _ in files]
    if entry is not None:
        try:
            entry.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            partial = entry.with_name(f"{entry.name}.{os.getpid()}.partial")
            partial.write_text(
                json.dumps(
                    {
                        "files": [list(f) for f in files],
                        "ranges": [list(r) for r in ranges],
                    }
                )
            )
            partial.replace(entry)
        except OSError as error:
            logger.warning(f"cannot keep the id ranges of {index.location} ({error})")
    return ranges


def _holds(kind: str, low: str | None, high: str | None, identifier: str) -> bool:
    """Whether the range ``low``..``high`` of a column of type ``kind`` may hold ``identifier``.

    Without bounds, or for a type compared neither as text nor as a number,
    the file may hold any id and is searched.
    """
    if low is None or high is None:
        return True
    kind = kind.upper()
    if kind.startswith(_TEXT_TYPES):
        return low <= identifier <= high
    if not kind.startswith(_NUMBER_TYPES):
        return True
    try:
        return float(low) <= float(identifier) <= float(high)
    except ValueError:
        # An identifier that is not a number never equals the text of one.
        return False


def _query_file(
    href: str,
    index: RetrievedIdIndex,
    identifier: str,
    store_options: dict | None,
):
    """Read the row of ``identifier`` in one index file, or None."""
    from app.provider.duckdb_ import connect

    target = index.href_column or index.path_column
    bbox = f'"{index.bbox_column}"' if index.bbox_column else "NULL"
    con = connect(href, store_options=store_options)
    # Column names come from the definition and were checked against the
    # file by `_read_range`; the identifier and the file are parameters.
    return con.execute(
        # ruff: ignore[hardcoded-sql-expression]
        f'SELECT "{target}", {bbox} FROM read_parquet(?)'  # nosec B608
        f' WHERE CAST("{index.id_column}" AS VARCHAR) = ? LIMIT 1',
        [href, identifier],
    ).fetchone()


def look_up_id(
    index: RetrievedIdIndex,
    identifier: str,
    *,
    store_options: dict | None = None,
    cache_dir: Path | None = None,
) -> IdRow | None:
    """Look ``identifier`` up in the index.

    An index that cannot be listed or read raises `IdIndexError`.

    Parameters
    ----------
    index
        The index.
    identifier
        The id, in its text form.
    store_options
        The storage settings of the index.
    cache_dir
        Where the id ranges of the index files are kept between runs.

    Returns
    -------
    IdRow | None
        The row of the id, or None when the index has none.
    """
    from app.provider.duckdb_ import load_duckdb

    duckdb = load_duckdb()
    try:
        return _look_up(index, identifier, store_options, cache_dir)
    except duckdb.Error as error:
        raise IdIndexError(f"the id index {index.location} cannot be read: {error}") from error


def _look_up(
    index: RetrievedIdIndex,
    identifier: str,
    store_options: dict | None,
    cache_dir: Path | None,
) -> IdRow | None:
    """Look ``identifier`` up in the one index file whose range may hold it."""
    for href, kind, low, high in _read_ranges(index, store_options, cache_dir):
        if not _holds(kind, low, high, identifier):
            continue
        row = _query_file(href, index, identifier, store_options)
        if row is None:
            continue
        target, bbox = row
        if target and index.path_column:
            target = f"{(index.href_base or '').rstrip('/')}/{str(target).lstrip('/')}"
        planar = None
        if isinstance(bbox, Mapping):
            planar = (
                float(bbox["xmin"]),
                float(bbox["ymin"]),
                float(bbox["xmax"]),
                float(bbox["ymax"]),
            )
        return IdRow(href=str(target) if target else None, bbox=planar)
    return None
