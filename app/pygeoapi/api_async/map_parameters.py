"""The parameters of one map request, checked and normalised once for every provider.

The route answers 400 for a parameter it cannot read and 413 for a map
above the collection's limits, before any provider is called. It moves
the bbox into the CRS of the map, clips it to that CRS and answers 204
when nothing is left to draw, so a provider only gets valid arguments.
"""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pygeoapi.api.maps as maps_api
from pygeoapi.api import APIRequest, validate_subset
from pygeoapi.crs import DEFAULT_CRS, get_uri, transform_bbox
from pyproj.exceptions import CRSError

from app.interfaces.providers import MapCapabilities, MapLimits
from app.provider.maps import WEB_MERCATOR, MapParameterError, MapTooLargeError
from app.pygeoapi.map_limits import default_map_crs

WEB_MERCATOR_EDGE = 20037508.342789244
"""How far Web Mercator goes from its origin, in metres, on both axes."""


@dataclass(frozen=True)
class MapParameters:
    """The checked arguments of one map, as the provider receives them.

    Attributes
    ----------
    style
        The name of the style in the path, or None for the default one.
    bbox
        ``(xmin, ymin, xmax, ymax)`` in ``crs``, clipped to it; ``xmin > xmax``
        means that the box crosses the antimeridian.
    width
        The width of the image in pixels.
    height
        The height of the image in pixels.
    crs
        The URI of the CRS of the map, written as the provider declares it.
    transparent
        Whether the background is transparent.
    format_
        The format the client asked for with ``f``.
    datetime_
        The ``datetime`` of the request, or None.
    subsets
        The values asked with ``subset``, by additional dimension, or None.
    """

    style: str | None
    bbox: tuple[float, float, float, float]
    width: int
    height: int
    crs: str
    transparent: bool
    format_: str
    datetime_: str | None
    subsets: dict[str, list[Any]] | None


def clip_bbox(
    bbox: tuple[float, float, float, float], crs: str
) -> tuple[float, float, float, float] | None:
    """The part of ``bbox`` inside the bounds of ``crs``.

    Only Web Mercator has bounds here; a bbox in another CRS comes back as
    it is. The coordinates that fall outside are moved to the edge, as
    /per/spatial-subsetting/map-outside-bounds allows.

    Parameters
    ----------
    bbox
        ``(xmin, ymin, xmax, ymax)`` in ``crs``; ``xmin > xmax`` crosses the
        antimeridian, and stays a crossing.
    crs
        The URI of the CRS of ``bbox``.

    Returns
    -------
    tuple of float or None
        The clipped bbox, or None when an axis lies entirely outside the
        bounds and there is nothing to draw.
    """
    if crs.lower() != WEB_MERCATOR.lower():
        return bbox
    xmin, ymin, xmax, ymax = bbox
    edge = WEB_MERCATOR_EDGE
    if ymin >= edge or ymax <= -edge:
        return None
    crossing = xmin > xmax
    if (not crossing and (xmin >= edge or xmax <= -edge)) or (
        crossing and xmin >= edge and xmax <= -edge
    ):
        return None
    return (_within(xmin, edge), _within(ymin, edge), _within(xmax, edge), _within(ymax, edge))


def parse_map_parameters(
    request: APIRequest,
    collection_def: dict[str, Any],
    extents: dict[str, Any],
    limits: MapLimits,
    capabilities: MapCapabilities,
    style: str | None,
) -> MapParameters | None:
    """Check the parameters of a map request against what the collection draws.

    Parameters
    ----------
    request
        The request.
    collection_def
        The definition of the collection's map provider.
    extents
        The collection's extents.
    limits
        The collection's limits, cut to the server's ceiling.
    capabilities
        The CRSs and formats the provider draws.
    style
        The style named in the path, or None.

    Returns
    -------
    MapParameters or None
        The arguments of the map, or None when the bbox lies entirely
        outside the CRS of the map.

    Raises
    ------
    MapParameterError
        For a parameter the route cannot read or the provider does not
        draw; the route answers 400.
    MapTooLargeError
        For a map above the collection's limits; the route answers 413.
    """
    params = request.params
    width = _positive_integer(params.get("width", 500), "width")
    height = _positive_integer(params.get("height", 300), "height")
    if width > limits.max_width or height > limits.max_height:
        largest = f"width must be at most {limits.max_width}"
        raise MapTooLargeError(user_msg=f"{largest} and height at most {limits.max_height}")
    if limits.max_pixels is not None and width * height > limits.max_pixels:
        raise MapTooLargeError(user_msg=f"width * height must be at most {limits.max_pixels}")

    crs = _declared(params.get("crs"), capabilities.crs, "crs") or default_map_crs(
        collection_def, capabilities
    )
    bbox_crs = _declared(params.get("bbox-crs"), (DEFAULT_CRS, *capabilities.crs), "bbox-crs")
    bbox_crs = bbox_crs or DEFAULT_CRS

    transparent = str(params.get("transparent", "true")).lower()
    if transparent not in ("true", "false"):
        raise MapParameterError(user_msg="transparent must be either true or false")

    format_ = params.get("f")
    asked = format_ if format_ is not None else request.format
    if asked is not None and asked != "html" and asked not in capabilities.formats:
        raise MapParameterError(user_msg=f"maps are drawn as {', '.join(capabilities.formats)}")

    bbox = _bbox(params.get("bbox"))
    if bbox[1] > bbox[3]:
        raise MapParameterError(user_msg="the bbox has its minimum y above its maximum y")
    if bbox[0] == bbox[2] or bbox[1] == bbox[3]:
        raise MapParameterError(user_msg="the bbox has no area")
    if bbox_crs.lower() != crs.lower():
        moved = transform_bbox(list(bbox), bbox_crs, crs, always_xy=True)
        bbox = (moved[0], moved[1], moved[2], moved[3])
    clipped = clip_bbox(bbox, crs)
    if clipped is None:
        return None

    try:
        datetime_ = maps_api.validate_datetime(extents, params.get("datetime"))
    except ValueError as error:
        raise MapParameterError(user_msg=str(error)) from None

    return MapParameters(
        style=style,
        bbox=clipped,
        width=width,
        height=height,
        crs=crs,
        transparent=transparent == "true",
        format_=format_ if format_ is not None else capabilities.formats[0],
        datetime_=datetime_,
        subsets=_subsets(params, extents),
    )


def format_content_datetime(extents: dict[str, Any]) -> str | None:
    """The ``Content-Datetime`` of a map of a collection, from its temporal extent.

    No native provider filters by time, so a map covers the whole temporal
    extent of its collection (/req/core/map-response).

    Parameters
    ----------
    extents
        The collection's extents.

    Returns
    -------
    str or None
        The instant, or the interval in RFC 3339 with ``..`` for an open
        end; None when the collection has no temporal extent.
    """
    temporal = extents.get("temporal") or {}
    begin, end = _instant(temporal.get("begin")), _instant(temporal.get("end"))
    if begin is None and end is None:
        return None
    if begin == end:
        return begin
    return f"{begin or '..'}/{end or '..'}"


def _instant(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _within(value: float, edge: float) -> float:
    return max(-edge, min(edge, value))


def _positive_integer(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number < 1:
        raise MapParameterError(user_msg=f"{name} must be a positive integer")
    return number


def _declared(value: str | None, declared: tuple[str, ...], name: str) -> str | None:
    """The declared URI ``value`` names, regardless of case and of URI or CURIE."""
    if value is None:
        return None
    try:
        uri = get_uri(value)
    except (ValueError, CRSError):
        uri = value
    for candidate in declared:
        if candidate.lower() == uri.lower():
            return candidate
    raise MapParameterError(user_msg=f"{name} must be one of {', '.join(declared)}")


def _bbox(value: str | None) -> tuple[float, float, float, float]:
    if value is None:
        xmin, ymin, xmax, ymax = maps_api.DEFAULT_BBOX
        return (float(xmin), float(ymin), float(xmax), float(ymax))
    parts = value.split(",")
    if len(parts) != 4:
        raise MapParameterError(user_msg="bbox values should be minx,miny,maxx,maxy")
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        raise MapParameterError(user_msg="bbox values must be numbers") from None
    if not all(math.isfinite(number) for number in numbers):
        raise MapParameterError(user_msg="bbox values must be finite numbers")
    return (numbers[0], numbers[1], numbers[2], numbers[3])


def _subsets(params: Any, extents: dict[str, Any]) -> dict[str, list[Any]] | None:
    if "subset" not in params:
        return None
    dimensions = deepcopy(extents)
    dimensions.pop("spatial", None)
    dimensions.pop("temporal", None)
    try:
        subsets = validate_subset(params["subset"] or "")
    except (AttributeError, ValueError) as error:
        raise MapParameterError(user_msg=f"Invalid subset: {error}") from None
    for key in subsets:
        if key not in dimensions:
            raise MapParameterError(user_msg=f"Subset not found; valid values are {dimensions}")
    return subsets
