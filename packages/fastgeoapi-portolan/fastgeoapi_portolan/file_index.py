"""The index of the files of a partitioned GeoParquet collection.

fastgeoapi reads, for a request with a bbox, only the files whose bbox
meets it, when the provider names an index of the files. The ingest
points the provider at the index the catalog publishes, or builds the
rows of one from the items it reads.
"""

from __future__ import annotations

import json
import posixpath
import re
import struct
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from fastgeoapi_portolan.catalog.locations import is_url

#: The stac-geoparquet metadata version written. The specification allows 1.0.0
#: and 1.1.0, its JSON schema only 1.0.0, and the reference writer writes 1.0.0.
STAC_GEOPARQUET_VERSION = "1.0.0"


@dataclass(frozen=True)
class IndexRow:
    """One file of a collection, as the index lists it.

    Attributes
    ----------
    id
        The id of the item that names the file.
    bbox
        ``(xmin, ymin, xmax, ymax)`` of the item.
    href
        Where the file is, as the provider reads it.
    """

    id: str
    bbox: tuple[float, float, float, float]
    href: str


def read_planar_bbox(bbox: object) -> tuple[float, float, float, float] | None:
    """The planar corners of a STAC bbox of 4 or 6 numbers, or None when it has neither.

    Parameters
    ----------
    bbox
        The ``bbox`` of an item.

    Returns
    -------
    tuple[float, float, float, float] | None
        ``(xmin, ymin, xmax, ymax)``.
    """
    if not isinstance(bbox, Sequence) or isinstance(bbox, str) or len(bbox) not in (4, 6):
        return None
    half = len(bbox) // 2
    try:
        return (float(bbox[0]), float(bbox[1]), float(bbox[half]), float(bbox[half + 1]))
    except (TypeError, ValueError):
        return None


_PLAIN_NAME = re.compile(r"[A-Za-z0-9._-]+")


def index_location(into: str, resource_id: str) -> str:
    """Name the index of ``resource_id`` beside the configuration ``into``.

    Parameters
    ----------
    into
        The configuration the ingest writes, a path or a bucket URL.
    resource_id
        The id of the resource the index is for.

    Returns
    -------
    str
        ``<folder of into>/indexes/<resource_id>.parquet``.

    Raises
    ------
    ValueError
        If ``resource_id`` is not a plain file name: the id comes from the
        catalog, and a path in it would write or delete another object.
    """
    if not _PLAIN_NAME.fullmatch(resource_id) or resource_id in (".", ".."):
        raise ValueError(f"the resource id {resource_id!r} is not a plain file name")
    name = f"{resource_id}.parquet"
    if is_url(into):
        parts = urlsplit(into)
        key = posixpath.normpath(str(PurePosixPath(parts.path).parent / "indexes" / name))
        return f"{parts.scheme}://{parts.netloc}{key}"
    return str(Path(into).resolve().parent / "indexes" / name)


def _polygon_wkb(bbox: tuple[float, float, float, float]) -> bytes:
    """The rectangle of ``bbox`` as a little-endian WKB polygon."""
    xmin, ymin, xmax, ymax = bbox
    if xmin > xmax:
        # A box across the antimeridian: the rectangle spans every longitude.
        xmin, xmax = -180.0, 180.0
    ring = [(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax), (xmin, ymin)]
    return struct.pack("<BIII", 1, 3, 1, len(ring)) + b"".join(
        struct.pack("<dd", x, y) for x, y in ring
    )


def _geo_metadata(rows: Sequence[IndexRow]) -> dict[str, Any]:
    """The GeoParquet 1.1 metadata of an index of ``rows``, with its bbox covering."""
    corners = [
        min(row.bbox[0] for row in rows),
        min(row.bbox[1] for row in rows),
        max(row.bbox[2] for row in rows),
        max(row.bbox[3] for row in rows),
    ]
    if any(row.bbox[0] > row.bbox[2] for row in rows):
        corners[0], corners[2] = -180.0, 180.0
    covering = {corner: ["bbox", corner] for corner in ("xmin", "ymin", "xmax", "ymax")}
    return {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": ["Polygon"],
                "bbox": corners,
                "covering": {"bbox": covering},
            }
        },
    }


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_index(
    rows: Sequence[IndexRow], location: str, store_options: Mapping[str, Any] | None = None
) -> None:
    """Write a stac-geoparquet file with one row per file of ``rows``.

    The file has the columns the specification requires (``stac_extensions``
    and ``links`` empty, ``id``, ``geometry`` as the WKB rectangle of the
    bbox, ``bbox`` and ``assets`` with the ``data`` href), a null
    ``datetime`` as the one property, the ``geo``
    metadata of GeoParquet 1.1 and the ``stac-geoparquet`` metadata. A local
    file is written in place; for a bucket it is written to a temporary file
    and then put.

    Parameters
    ----------
    rows
        The files, at least one.
    location
        Where the index goes, a path or a bucket URL.
    store_options
        The storage settings of the bucket.
    """
    import duckdb
    import obstore

    from fastgeoapi_portolan.storage import store_and_key

    con = duckdb.connect()
    con.execute(
        "CREATE TABLE files (id VARCHAR, xmin DOUBLE, ymin DOUBLE, xmax DOUBLE,"
        " ymax DOUBLE, href VARCHAR, geometry BLOB)"
    )
    con.executemany(
        "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(row.id, *row.bbox, row.href, _polygon_wkb(row.bbox)) for row in rows],
    )
    stac = json.dumps({"version": STAC_GEOPARQUET_VERSION})
    geo = json.dumps(_geo_metadata(rows))
    select = (
        "SELECT []::VARCHAR[] AS stac_extensions, id, geometry,"
        " {'xmin': xmin, 'ymin': ymin, 'xmax': xmax, 'ymax': ymax} AS bbox,"
        " []::STRUCT(href VARCHAR, rel VARCHAR, type VARCHAR)[] AS links,"
        " {'data': {'href': href, 'type': 'application/vnd.apache.parquet', 'roles': ['data']}}"
        " AS assets,"
        # STAC items carry `datetime` among their properties; the reference reader
        # rebuilds them from the columns past the top-level ones and needs one.
        " NULL::TIMESTAMPTZ AS datetime"
        " FROM files"
    )
    metadata = f'{{"stac-geoparquet": {_quoted(stac)}, geo: {_quoted(geo)}}}'
    options = f"FORMAT parquet, KV_METADATA {metadata}"
    if not is_url(location):
        Path(location).parent.mkdir(parents=True, exist_ok=True)
        # The values are bound into `files`; the metadata and the location are quoted.
        con.execute(f"COPY ({select}) TO {_quoted(location)} ({options})")  # nosec B608
        return
    with tempfile.TemporaryDirectory() as folder:
        staged = Path(folder) / "index.parquet"
        con.execute(f"COPY ({select}) TO {_quoted(str(staged))} ({options})")  # nosec B608
        store, key = store_and_key(location, store_options)
        obstore.put(store, key, staged.read_bytes())


def delete_index(location: str, store_options: Mapping[str, Any] | None = None) -> None:
    """Delete the index at ``location``; one that is not there is no error.

    Parameters
    ----------
    location
        The index, a path or a bucket URL.
    store_options
        The storage settings of the bucket.
    """
    import obstore

    from fastgeoapi_portolan.storage import store_and_key

    if not is_url(location):
        Path(location).unlink(missing_ok=True)
        return
    store, key = store_and_key(location, store_options)
    try:
        obstore.delete(store, key)
    except FileNotFoundError:
        pass
