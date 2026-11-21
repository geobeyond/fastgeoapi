"""The bounds of Web Mercator, and how a bbox is held within them.

Web Mercator draws the sphere of radius 6378137 m on a square: x and y run
from ``-WEB_MERCATOR_EDGE`` to ``WEB_MERCATOR_EDGE``, and the latitudes
beyond ``WEB_MERCATOR_MAX_LATITUDE`` fall outside it.
"""

from __future__ import annotations

import math

WEB_MERCATOR_EDGE = math.pi * 6378137
"""How far Web Mercator goes from its origin, in metres, on both axes."""

WEB_MERCATOR_MAX_LATITUDE = math.degrees(math.atan(math.sinh(math.pi)))
"""The latitude where y reaches ``WEB_MERCATOR_EDGE``, in degrees."""


def is_outside_web_mercator(bbox: tuple[float, float, float, float]) -> bool:
    """Tell whether ``bbox`` lies entirely beyond an edge of Web Mercator.

    Parameters
    ----------
    bbox
        ``(xmin, ymin, xmax, ymax)`` in Web Mercator; ``xmin > xmax``
        crosses the antimeridian.

    Returns
    -------
    bool
        True when an axis has no value within the edges, so that nothing is
        left to draw.
    """
    xmin, ymin, xmax, ymax = bbox
    edge = WEB_MERCATOR_EDGE
    if ymin >= edge or ymax <= -edge:
        return True
    if xmin > xmax:
        return xmin >= edge and xmax <= -edge
    return xmin >= edge or xmax <= -edge


def clip_web_mercator_bbox(
    bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Move the coordinates of ``bbox`` beyond the edges of Web Mercator onto them.

    /per/spatial-subsetting/map-outside-bounds allows it. A bbox that lies
    entirely outside, as :func:`is_outside_web_mercator` tells, comes
    back as a line on an edge.

    Parameters
    ----------
    bbox
        ``(xmin, ymin, xmax, ymax)`` in Web Mercator; ``xmin > xmax``
        crosses the antimeridian, and stays a crossing.

    Returns
    -------
    tuple of float
        The bbox within the edges.
    """
    edge = WEB_MERCATOR_EDGE
    xmin, ymin, xmax, ymax = (max(-edge, min(edge, value)) for value in bbox)
    return (xmin, ymin, xmax, ymax)
