"""The index of the files of a partitioned GeoParquet collection.

fastgeoapi reads, for a request with a bbox, only the files whose bbox
meets it, when the provider names an index of the files. The ingest
points the provider at the index the catalog publishes, or builds the
rows of one from the items it reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


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
