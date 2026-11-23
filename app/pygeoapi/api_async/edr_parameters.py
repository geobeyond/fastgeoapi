"""Check and normalise the parameters of one EDR query, the same way for every provider.

A parameter that cannot be read is refused with 400, a query type the
collection does not offer with 404, and a place outside the extent is
answered with 204, all before any provider is called.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pygeoapi.api.maps as maps_api
from pygeoapi.api import APIRequest
from pygeoapi.crs import get_uri
from pygeoapi.util import get_choice_from_headers
from pyproj.exceptions import CRSError
from shapely import wkt
from shapely.errors import ShapelyError
from shapely.geometry import MultiPoint, MultiPolygon, Point, Polygon, box

from app.interfaces.ogc import OGC_CRS_CRS84, OGC_CRS_CRS84H
from app.interfaces.providers import (
    AreaQuery,
    EdrCapabilities,
    EdrFormat,
    EdrQuery,
    PositionQuery,
)
from app.provider.edr import (
    EdrNotAcceptableError,
    EdrParameterError,
    EdrQueryNotOfferedError,
)
from app.schemas.temporal import TimeInterval, parse_ogc_datetime

OGC_EDR_PARAMETERS = frozenset(
    {
        "bbox",
        "coords",
        "corridor-height",
        "corridor-width",
        "crs",
        "cube-z",
        "datetime",
        "f",
        "height-units",
        "lang",
        "limit",
        "parameter-name",
        "resolution-x",
        "resolution-y",
        "resolution-z",
        "width-units",
        "within",
        "within-units",
        "z",
    }
)
"""The query parameters of OGC API - EDR, and pygeoapi's ``lang``.

Whether or not the route reads them, they never reach the provider as
vendor parameters.
"""

_OGC_CURIES = {"ogc:crs84h": OGC_CRS_CRS84H}
"""The OGC CURIEs pygeoapi's get_uri does not read, by their lower case."""

_GEOMETRIES = {
    "position": (Point, MultiPoint, "a POINT or a MULTIPOINT"),
    "area": (Polygon, MultiPolygon, "a POLYGON or a MULTIPOLYGON"),
}


@dataclass(frozen=True)
class EdrOutsideExtent:
    """A query whose place lies entirely outside the spatial extent of the collection.

    ``parse_edr_query`` returns it instead of an ``EdrQuery``: the caller
    matches on the type, and the type checker makes it handle both. The
    route answers 204 without calling the provider.
    """


def parse_edr_query(
    request: APIRequest,
    collection: dict[str, Any],
    query_type: str,
    capabilities: EdrCapabilities,
    max_values: int,
) -> EdrQuery | EdrOutsideExtent:
    """Check the parameters of an EDR query against what the collection offers.

    Parameters
    ----------
    request
        The request.
    collection
        The collection's configuration, whose ``extents`` bound the query.
    query_type
        The query type of the path, such as ``position``.
    capabilities
        The query types, CRSs, formats and parameters the provider offers.
    max_values
        The most values the query may return, set on the result.

    Returns
    -------
    PositionQuery or AreaQuery or EdrOutsideExtent
        The checked query, or ``EdrOutsideExtent`` when its place does not
        meet the spatial extent. The extent is in CRS84, so a query in
        another CRS is never found outside it.

    Raises
    ------
    EdrQueryNotOfferedError
        For a query type the provider does not offer; the route answers 404.
    EdrParameterError
        For a parameter the route cannot read or the collection does not
        offer; the route answers 400.
    EdrNotAcceptableError
        For an ``Accept`` that names no offered format; the route answers
        406.
    """
    if query_type not in capabilities.query_types or query_type not in _GEOMETRIES:
        raise EdrQueryNotOfferedError(user_msg=f"query type {query_type} is not offered")
    params = request.params
    extents = collection.get("extents") or {}

    crs = _match_declared_crs(params.get("crs"), capabilities.crs, capabilities.default_crs)
    format_ = _choose_edr_format(params.get("f"), request.headers, capabilities.formats)
    coords = _parse_coords(params.get("coords"), query_type)
    parameter_names = _parse_parameter_names(params.get("parameter-name"), capabilities)
    if params.get("z") is not None:
        raise EdrParameterError(user_msg="the collection has no vertical axis, z is not accepted")

    try:
        processed = maps_api.validate_datetime(extents, params.get("datetime"))
        datetime_ = None if processed is None else parse_ogc_datetime(processed)
    except ValueError as error:
        raise EdrParameterError(user_msg=str(error)) from None

    if crs.lower() == OGC_CRS_CRS84.lower() and _is_outside_extent(coords, extents):
        return EdrOutsideExtent()

    vendor_params = {
        name: str(value) for name, value in params.items() if name not in OGC_EDR_PARAMETERS
    }
    if query_type == "position":
        return PositionQuery(
            coords=coords,
            parameter_names=parameter_names,
            datetime_=datetime_,
            crs=crs,
            format_=format_,
            max_values=max_values,
            vendor_params=vendor_params,
        )
    return AreaQuery(
        coords=coords,
        parameter_names=parameter_names,
        datetime_=datetime_,
        crs=crs,
        format_=format_,
        max_values=max_values,
        vendor_params=vendor_params,
        resolution_x=_parse_resolution(params.get("resolution-x"), "resolution-x"),
        resolution_y=_parse_resolution(params.get("resolution-y"), "resolution-y"),
    )


def describe_edr_query(query: EdrQuery) -> dict[str, Any]:
    """Describe a query as JSON-ready values, to build a cache key from it.

    Parameters
    ----------
    query
        The checked query.

    Returns
    -------
    dict
        The geometry as WKT, the datetime as ISO text, and every other
        field of the query by name; the vendor parameters are sorted.
    """
    description: dict[str, Any] = {
        "kind": "area" if isinstance(query, AreaQuery) else "position",
        "coords": query.coords.wkt,
        "parameter_names": list(query.parameter_names),
        "datetime": _format_datetime(query.datetime_),
        "crs": query.crs,
        "format": str(query.format_),
        "max_values": query.max_values,
        "vendor_params": dict(sorted(query.vendor_params.items())),
    }
    if isinstance(query, AreaQuery):
        description["resolution_x"] = query.resolution_x
        description["resolution_y"] = query.resolution_y
    return description


def _format_datetime(value: datetime | TimeInterval | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    start, end = (".." if moment is None else moment.isoformat() for moment in value)
    return f"{start}/{end}"


def _match_declared_crs(value: str | None, declared: tuple[str, ...], default: str) -> str:
    """Find the declared URI ``value`` names, in any case and as a URI or a CURIE.

    Parameters
    ----------
    value
        The ``crs`` of the request, as the client wrote it, or None.
    declared
        The URIs of the CRSs the provider declares.
    default
        The URI for a request without the parameter.

    Returns
    -------
    str
        The declared URI, written as declared, or ``default`` when
        ``value`` is None.

    Raises
    ------
    EdrParameterError
        When ``value`` names no declared CRS.
    """
    if value is None:
        return default
    try:
        uri = get_uri(value)
    except (ValueError, CRSError):
        uri = value
    if not isinstance(uri, str):
        # pygeoapi returns the CRSError of a CURIE it cannot read instead of raising it.
        uri = _OGC_CURIES.get(value.strip("[]").lower(), value)
    for candidate in declared:
        if candidate.lower() == uri.lower():
            return candidate
    raise EdrParameterError(user_msg=f"crs must be one of {', '.join(declared)}")


def _choose_edr_format(f: str | None, headers: Any, formats: tuple[EdrFormat, ...]) -> str:
    """Choose the format of the response from ``f``, else from ``Accept``.

    Parameters
    ----------
    f
        The ``f`` parameter, or None.
    headers
        The headers of the request.
    formats
        The formats the provider offers, its default first.

    Returns
    -------
    str
        The format to answer in. Without ``f``, the first media type of
        ``Accept`` that the provider offers wins; ``*/*`` and
        ``application/*`` take the first format, and so does a request
        without ``Accept``.

    Raises
    ------
    EdrParameterError
        For an ``f`` the provider does not offer.
    EdrNotAcceptableError
        For an ``Accept`` that names no offered format and no wildcard.
    """
    media_types = {str(format_): EdrFormat(format_).media_type for format_ in formats}
    names = tuple(media_types)
    if f is not None:
        if f not in media_types:
            raise EdrParameterError(user_msg=f"data is returned as {', '.join(names)}")
        return f
    accepted = get_choice_from_headers(headers, "accept", all=True)
    if not accepted:
        return names[0]
    by_media_type = {media_type: format_ for format_, media_type in media_types.items()}
    for media_type in (value.strip().lower() for value in accepted):
        if media_type in by_media_type:
            return by_media_type[media_type]
        if media_type in ("*/*", "application/*"):
            return names[0]
    raise EdrNotAcceptableError(user_msg=f"data is returned as {', '.join(by_media_type)}")


def _parse_coords(value: str | None, query_type: str) -> Any:
    if value is None or not value.strip():
        raise EdrParameterError(user_msg="coords is required")
    try:
        geometry = wkt.loads(value)
    except (ShapelyError, ValueError, TypeError):
        raise EdrParameterError(user_msg="coords must be well-known text (WKT)") from None
    single, multiple, label = _GEOMETRIES[query_type]
    if geometry.is_empty or not isinstance(geometry, (single, multiple)):
        raise EdrParameterError(user_msg=f"a {query_type} query takes {label} in coords")
    return geometry


def _parse_parameter_names(value: str | None, capabilities: EdrCapabilities) -> tuple[str, ...]:
    offered = tuple(parameter.name for parameter in capabilities.parameters)
    names = tuple(name.strip() for name in (value or "").split(",") if name.strip())
    if not names:
        return offered
    unknown = [name for name in names if name not in offered]
    if unknown:
        raise EdrParameterError(
            user_msg=f"unknown parameter-name {', '.join(unknown)}; the collection offers "
            f"{', '.join(offered)}"
        )
    return names


def _parse_resolution(value: str | None, name: str) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise EdrParameterError(user_msg=f"{name} must be a positive integer")
    return number


def _is_outside_extent(coords: Any, extents: dict[str, Any]) -> bool:
    boxes = (extents.get("spatial") or {}).get("bbox") or ()
    if not boxes:
        return False
    return not any(coords.intersects(box(*extent[:4])) for extent in boxes)
