"""Check and normalise the parameters of one map request, the same way for every provider.

A parameter that cannot be read is refused with 400, and a map above the
collection's limits with 413, before any provider is called. The bbox is
moved into the CRS of the map and clipped to it; when nothing is left to
draw, the answer is 204.
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

from app.interfaces.ogc import OGC_CRS_WEB_MERCATOR
from app.interfaces.providers import MapCapabilities, MapLimits, MapParameters
from app.maps.web_mercator import clip_web_mercator_bbox, is_outside_web_mercator
from app.provider.maps import (
    MapParameterError,
    MapStyleNotFoundError,
    MapTooLargeError,
)
from app.schemas.temporal import parse_ogc_datetime

OGC_MAP_PARAMETERS = frozenset(
    {
        "bbox",
        "bbox-crs",
        "bgcolor",
        "center",
        "center-crs",
        "collections",
        "crs",
        "crs-datum",
        "crs-proj-center",
        "crs-proj-method",
        "crs-proj-params",
        "datetime",
        "f",
        "height",
        "lang",
        "mm-per-pixel",
        "orientation",
        "scale-denominator",
        "subset",
        "subset-crs",
        "transparent",
        "void-color",
        "void-transparent",
        "width",
    }
)
"""The query parameters of OGC API - Maps, and pygeoapi's ``lang``.

Whether or not the route reads them, they never reach the provider as
vendor parameters.
"""


@dataclass(frozen=True)
class MapOutsideCrs:
    """A map whose bbox lies entirely outside the bounds of its CRS.

    ``parse_map_parameters`` returns it instead of ``MapParameters``, as
    the second variant of a typed result: the caller matches on the type,
    and the type checker makes it handle both. The route answers 204
    without calling the provider; /req/spatial-subsetting asks for 204 or
    404 when the values fall entirely outside the valid range of an axis.

    Attributes
    ----------
    bbox
        ``(xmin, ymin, xmax, ymax)`` the client asked for, moved into
        ``crs`` and not clipped.
    crs
        The URI of the CRS of the map.
    """

    bbox: tuple[float, float, float, float]
    crs: str


def parse_map_parameters(
    request: APIRequest,
    collection: dict[str, Any],
    limits: MapLimits,
    capabilities: MapCapabilities,
    style: str | None,
) -> MapParameters | MapOutsideCrs:
    """Check the parameters of a map request against what the collection draws.

    Parameters
    ----------
    request
        The request.
    collection
        The collection's configuration, whose ``extents`` bound the map.
    limits
        The collection's limits, clamped to the server's.
    capabilities
        The CRSs, the default CRS, the formats and the styles the provider
        draws.
    style
        The style named in the path, or None for the default one.

    Returns
    -------
    MapParameters or MapOutsideCrs
        The parameters of the map, or ``MapOutsideCrs`` when the bbox lies
        entirely outside the bounds of the CRS of the map.

    Raises
    ------
    MapStyleNotFoundError
        For a style the provider does not declare; the route answers 404.
    MapParameterError
        For a parameter the route cannot read or the provider does not
        draw; the route answers 400.
    MapTooLargeError
        For a map above the collection's limits; the route answers 413.
    """
    if style is not None and style not in capabilities.styles:
        raise MapStyleNotFoundError(user_msg=f"style {style} not found")
    params = request.params
    extents = collection["extents"]
    width = _parse_positive_integer(params.get("width", 500), "width")
    height = _parse_positive_integer(params.get("height", 300), "height")
    if width > limits.max_width or height > limits.max_height:
        largest = f"width must be at most {limits.max_width}"
        raise MapTooLargeError(user_msg=f"{largest} and height at most {limits.max_height}")
    if limits.max_pixels is not None and width * height > limits.max_pixels:
        raise MapTooLargeError(user_msg=f"width * height must be at most {limits.max_pixels}")

    crs = _match_declared_crs(params.get("crs"), capabilities.crs, capabilities.default_crs, "crs")
    bbox_crs = _match_declared_crs(
        params.get("bbox-crs"), (DEFAULT_CRS, *capabilities.crs), DEFAULT_CRS, "bbox-crs"
    )

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
    if crs.lower() == OGC_CRS_WEB_MERCATOR.lower():
        if is_outside_web_mercator(bbox):
            return MapOutsideCrs(bbox=bbox, crs=crs)
        bbox = clip_web_mercator_bbox(bbox)

    try:
        processed_datetime = maps_api.validate_datetime(extents, params.get("datetime"))
        datetime_ = None if processed_datetime is None else parse_ogc_datetime(processed_datetime)
    except ValueError as error:
        raise MapParameterError(user_msg=str(error)) from None

    return MapParameters(
        style=style,
        bbox=bbox,
        width=width,
        height=height,
        crs=crs,
        transparent=transparent == "true",
        # Without f, and for f=html, the map is drawn in the first format the provider declares.
        format_=asked if asked in capabilities.formats else capabilities.formats[0],
        datetime_=datetime_,
        subsets=_parse_subsets(params, extents),
        vendor_params=_collect_vendor_params(params),
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


def _parse_positive_integer(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number < 1:
        raise MapParameterError(user_msg=f"{name} must be a positive integer")
    return number


def _match_declared_crs(
    value: str | None, declared: tuple[str, ...], default: str, name: str
) -> str:
    """Find the declared URI ``value`` names, in any case and as a URI or a CURIE.

    Parameters
    ----------
    value
        The CRS of the request, as the client wrote it, or None.
    declared
        The URIs of the CRSs the provider declares.
    default
        The URI for a request without the parameter.
    name
        The name of the request parameter, for the error message.

    Returns
    -------
    str
        The declared URI, written as declared, or ``default`` when
        ``value`` is None.

    Raises
    ------
    MapParameterError
        When ``value`` names no declared CRS; the route answers 400.
    """
    if value is None:
        return default
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


def _collect_vendor_params(params: Any) -> dict[str, str]:
    return {name: str(value) for name, value in params.items() if name not in OGC_MAP_PARAMETERS}


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
