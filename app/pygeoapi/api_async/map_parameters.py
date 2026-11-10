"""Check and normalise the parameters of one map request, the same way for every provider.

A parameter that cannot be read is refused with 400, and a map above the
collection's limits with 413, before any provider is called. The bbox is
moved into the CRS of the map and clipped to it; when nothing is left to
draw, the answer is 204.
"""

from __future__ import annotations

import math
from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Any

import pygeoapi.api.maps as maps_api
from pygeoapi.api import APIRequest, validate_subset
from pygeoapi.crs import DEFAULT_CRS, get_uri, transform_bbox
from pyproj.exceptions import CRSError

from app.interfaces.providers import MapCapabilities, MapLimits, MapParameters
from app.provider.maps import WEB_MERCATOR, MapParameterError, MapTooLargeError
from app.pygeoapi.map_limits import choose_default_map_crs

WEB_MERCATOR_EDGE = 20037508.342789244
"""How far Web Mercator goes from its origin, in metres, on both axes."""


def clip_bbox(
    bbox: tuple[float, float, float, float], crs: str
) -> tuple[float, float, float, float] | None:
    """Clip ``bbox`` to the bounds of ``crs``.

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
    return (
        _clamp_to_edge(xmin, edge),
        _clamp_to_edge(ymin, edge),
        _clamp_to_edge(xmax, edge),
        _clamp_to_edge(ymax, edge),
    )


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
        The parameters of the map, or None when the bbox lies entirely
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
    width = _parse_positive_integer(params.get("width", 500), "width")
    height = _parse_positive_integer(params.get("height", 300), "height")
    if width > limits.max_width or height > limits.max_height:
        largest = f"width must be at most {limits.max_width}"
        raise MapTooLargeError(user_msg=f"{largest} and height at most {limits.max_height}")
    if limits.max_pixels is not None and width * height > limits.max_pixels:
        raise MapTooLargeError(user_msg=f"width * height must be at most {limits.max_pixels}")

    crs = _match_declared_crs(params.get("crs"), capabilities.crs, "crs") or choose_default_map_crs(
        collection_def, capabilities
    )
    bbox_crs = _match_declared_crs(
        params.get("bbox-crs"), (DEFAULT_CRS, *capabilities.crs), "bbox-crs"
    )
    bbox_crs = bbox_crs or DEFAULT_CRS

    transparent = str(params.get("transparent", "true")).lower()
    if transparent not in ("true", "false"):
        raise MapParameterError(user_msg="transparent must be either true or false")

    format_ = params.get("f")
    asked = format_ if format_ is not None else request.format
    if asked is not None and asked != "html" and asked not in capabilities.formats:
        raise MapParameterError(user_msg=f"maps are drawn as {', '.join(capabilities.formats)}")

    if params.get("bbox") is None:
        # Without a bbox the map covers the collection, in the CRS of its extent.
        spatial = extents.get("spatial") or {}
        bbox = _parse_bbox(",".join(str(value) for value in spatial.get("bbox") or ()))
        bbox_crs = spatial.get("crs") or DEFAULT_CRS
    else:
        bbox = _parse_bbox(params.get("bbox"))
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
        # Without f, and for f=html, the map is drawn in the first format the provider declares.
        format_=asked if asked in capabilities.formats else capabilities.formats[0],
        datetime_=datetime_,
        subsets=_parse_subsets(params, extents),
    )


def format_content_datetime(extents: dict[str, Any]) -> str | None:
    """Format the ``Content-Datetime`` of a map from its collection's temporal extent.

    A native map is not filtered by time, so it covers the whole temporal
    extent (/req/core/map-response).

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
    begin, end = _format_instant(temporal.get("begin")), _format_instant(temporal.get("end"))
    if begin is None and end is None:
        return None
    if begin == end:
        return begin
    return f"{begin or '..'}/{end or '..'}"


def _format_instant(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _clamp_to_edge(value: float, edge: float) -> float:
    return max(-edge, min(edge, value))


def _parse_positive_integer(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number < 1:
        raise MapParameterError(user_msg=f"{name} must be a positive integer")
    return number


def _match_declared_crs(value: str | None, declared: tuple[str, ...], name: str) -> str | None:
    """Find the declared URI ``value`` names, in any case and as a URI or a CURIE.

    Parameters
    ----------
    value
        The CRS of the request, as the client wrote it, or None.
    declared
        The URIs of the CRSs the provider declares.
    name
        The name of the request parameter, for the error message.

    Returns
    -------
    str or None
        The declared URI, written as declared, or None when ``value`` is None.

    Raises
    ------
    MapParameterError
        When ``value`` names no declared CRS; the route answers 400.
    """
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


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
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


def _parse_subsets(params: Any, extents: dict[str, Any]) -> dict[str, list[Any]] | None:
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
