"""Maps served with ``await`` when the provider is natively async.

Mirrors ``pygeoapi/api/maps.py::get_collection_map`` step by step: the
same parameters, the same headers, the same errors. The one difference
is that the provider is awaited on the event loop instead of being
called in the threadpool.
"""

from __future__ import annotations

from copy import deepcopy
from http import HTTPStatus
from typing import Any

import pygeoapi.api.maps as maps_api
from pygeoapi import plugin as pygeoapi_plugin
from pygeoapi.api import API, APIRequest, validate_subset
from pygeoapi.crs import DEFAULT_CRS, get_uri, transform_bbox
from pygeoapi.formats import F_JSON, FORMAT_TYPES
from pygeoapi.provider import get_provider_by_type
from pygeoapi.provider.base import (
    ProviderGenericError,
    ProviderInvalidDataError,
    ProviderTypeError,
)
from pygeoapi.util import filter_dict_by_key_value, to_json

from app.interfaces.providers import AsyncMapProvider


def native_map_provider(api: API, dataset: str) -> tuple[dict, AsyncMapProvider] | None:
    """The collection's map provider definition and instance, when native async."""
    collections = filter_dict_by_key_value(api.config["resources"], "type", "collection")
    if dataset not in collections:
        return None
    try:
        provider_def = get_provider_by_type(api.config["resources"][dataset]["providers"], "map")
        provider = pygeoapi_plugin.load_plugin("provider", provider_def)
    except (KeyError, ProviderTypeError, ProviderGenericError):
        return None
    if isinstance(provider, AsyncMapProvider) and provider.native_async:
        return provider_def, provider
    return None


def _bad(api: API, headers: dict, description: str) -> tuple[dict, int, Any]:
    headers["Content-type"] = "application/json"
    exception = {"code": "InvalidParameterValue", "description": description}
    return headers, HTTPStatus.BAD_REQUEST, to_json(exception, api.pretty_print)


async def get_collection_map(
    api: API,
    request: APIRequest,
    dataset: str,
    style: str | None,
    collection_def: dict,
    provider: AsyncMapProvider,
) -> tuple[dict, int, Any]:
    """``(headers, status, content)`` for one map, awaiting the provider."""
    query_args: dict[str, Any] = {}
    format_ = request.format or "png"
    headers = request.get_response_headers(**api.api_headers)

    query_args["format_"] = request.params.get("f", "png")
    query_args["style"] = style
    try:
        if "crs" not in request.params:
            query_args["crs"] = collection_def.get("storage_crs", DEFAULT_CRS)
        else:
            query_args["crs"] = get_uri(request.params["crs"])
    except KeyError:
        query_args["crs"] = DEFAULT_CRS
    try:
        if "bbox-crs" not in request.params:
            query_args["bbox-crs"] = DEFAULT_CRS
        else:
            query_args["bbox-crs"] = get_uri(request.params["bbox-crs"])
    except KeyError:
        query_args["bbox-crs"] = DEFAULT_CRS

    query_args["transparent"] = request.params.get("transparent", True)
    try:
        query_args["width"] = int(request.params.get("width", 500))
        query_args["height"] = int(request.params.get("height", 300))
    except ValueError:
        return _bad(api, headers, "invalid width/height")

    try:
        bbox = request.params.get("bbox").split(",")
        if len(bbox) != 4:
            return _bad(api, headers, "bbox values should be minx,miny,maxx,maxy")
    except AttributeError:
        bbox = maps_api.DEFAULT_BBOX
    try:
        bbox = [float(c) for c in bbox]
    except ValueError:
        return _bad(api, headers, "bbox values must be numbers")
    if query_args["bbox-crs"] != query_args["crs"]:
        bbox = transform_bbox(bbox, query_args["bbox-crs"], query_args["crs"], always_xy=True)
    query_args["bbox"] = bbox

    datetime_ = request.params.get("datetime")
    try:
        query_args["datetime_"] = maps_api.validate_datetime(
            api.config["resources"][dataset]["extents"], datetime_
        )
    except ValueError as err:
        return api.get_exception(
            HTTPStatus.BAD_REQUEST, headers, request.format, "InvalidParameterValue", str(err)
        )

    if "subset" in request.params:
        subsets = deepcopy(api.config["resources"][dataset]["extents"])
        subsets.pop("spatial", None)
        subsets.pop("temporal", None)
        try:
            query_args["subsets"] = validate_subset(request.params["subset"] or "")
        except (AttributeError, ValueError) as err:
            return api.get_exception(
                HTTPStatus.BAD_REQUEST,
                headers,
                format_,
                "InvalidParameterValue",
                f"Invalid subset: {err}",
            )
        for key in query_args["subsets"]:
            if key not in subsets:
                return api.get_exception(
                    HTTPStatus.BAD_REQUEST,
                    headers,
                    format_,
                    "InvalidParameterValue",
                    f"Subset not found; valid values are {subsets}",
                )

    try:
        data = await provider.aquery(**query_args)
    except (ProviderGenericError, ProviderInvalidDataError) as err:
        headers["Content-Type"] = FORMAT_TYPES[F_JSON]
        # A provider error may say when to try again, as a full queue does.
        retry_after = getattr(err, "retry_after", None)
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        return api.get_exception(
            err.http_status_code, headers, request.format, err.ogc_exception_code, err.message
        )

    headers["Content-Crs"] = query_args["crs"]
    headers["Content-Bbox"] = ",".join(map(str, query_args["bbox"]))
    mt = collection_def["format"]["name"]
    if format_ == mt or format_ in (None, "html"):
        headers["Content-Type"] = collection_def["format"]["mimetype"]
        return headers, HTTPStatus.OK, data
    headers["Content-type"] = "application/json"
    exception = {"code": "InvalidParameterValue", "description": "invalid format parameter"}
    return headers, HTTPStatus.BAD_REQUEST, to_json(exception, api.pretty_print)
