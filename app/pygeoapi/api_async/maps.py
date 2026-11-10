"""Maps served with ``await`` when the provider is natively async.

The route answers what ``pygeoapi/api/maps.py::get_collection_map``
answers, with the same headers, and differs in three ways. The provider
is awaited on the event loop instead of being called in the threadpool.
The parameters are checked once, by :mod:`.map_parameters`, before the
provider is called. And the provider gets the contract's arguments only:
the route moves the bbox into ``crs`` and keeps ``bbox-crs`` for itself.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from pygeoapi import plugin as pygeoapi_plugin
from pygeoapi.api import API, APIRequest
from pygeoapi.formats import F_JSON, FORMAT_TYPES
from pygeoapi.provider import get_provider_by_type
from pygeoapi.provider.base import (
    ProviderGenericError,
    ProviderInvalidDataError,
    ProviderTypeError,
)
from pygeoapi.util import filter_dict_by_key_value, get_from_headers

from app.interfaces.providers import AsyncMapProvider, MapFormat
from app.provider.maps import MapParameterError
from app.pygeoapi.api_async.caching import (
    HttpCache,
    answer_not_modified,
    get_cache_headers,
    is_not_modified,
)
from app.pygeoapi.api_async.map_parameters import format_content_datetime, parse_map_parameters
from app.pygeoapi.map_limits import MapCeiling, cut_limits_to_ceiling, get_default_map_ceiling


def find_native_map_provider(api: API, dataset: str) -> tuple[dict, AsyncMapProvider] | None:
    """The map provider of a collection, when it is native async.

    Parameters
    ----------
    api
        pygeoapi's API instance.
    dataset
        The collection's name.

    Returns
    -------
    tuple of (dict, AsyncMapProvider) or None
        The provider's definition and its instance. None when the collection
        does not exist, or its map provider does not load or is not native;
        pygeoapi's route then serves the map.
    """
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


async def get_collection_map(
    api: API,
    request: APIRequest,
    dataset: str,
    style: str | None,
    collection_def: dict,
    provider: AsyncMapProvider,
    http_cache: HttpCache | None = None,
    map_ceiling: MapCeiling | None = None,
) -> tuple[dict, int, Any]:
    """Answer one map request, awaiting the provider.

    Parameters
    ----------
    api
        pygeoapi's API instance.
    request
        The request.
    dataset
        The collection's name.
    style
        The style named in the path, or None.
    collection_def
        The definition of the collection's map provider.
    provider
        The collection's map provider.
    http_cache
        The cache policy. With it, a provider that knows its version gives
        the map an ``ETag``, and a request that names it gets a 304 without
        the map being drawn. The version is read again after the draw, and
        a map whose version changed meanwhile gets no cache headers.
    map_ceiling
        The server's ceiling on map sizes; None takes the one of the
        settings. The map is held to the smaller of it and the provider's
        limits.

    Returns
    -------
    tuple of (dict, int, Any)
        The headers, the status and the content: 400 for a parameter the
        route cannot read or the provider does not draw, 413 above the
        limits, 204 for a bbox entirely outside the CRS of the map.
    """
    headers = request.get_response_headers(**api.api_headers)
    ceiling = map_ceiling if map_ceiling is not None else get_default_map_ceiling()
    limits = cut_limits_to_ceiling(provider.limits, ceiling)
    try:
        parameters = parse_map_parameters(
            request,
            collection_def,
            api.config["resources"][dataset]["extents"],
            limits,
            provider.capabilities,
            style,
        )
    except MapParameterError as error:
        refused = error
    else:
        refused = None
    # Answered outside the except block: pygeoapi logs the exception being
    # handled with its traceback, and a refused map is not a server error.
    if refused is not None:
        return _answer_error(api, request, headers, refused)
    if parameters is None:
        return headers, HTTPStatus.NO_CONTENT, b""

    cached = await get_cache_headers(http_cache, provider, dataset, "map", parameters, headers)
    asked = get_from_headers(request.headers, "if-none-match")
    media_type = MapFormat(parameters.format_).media_type
    if cached and is_not_modified(asked, cached["ETag"]):
        headers["Content-Type"] = media_type
        return answer_not_modified(headers, cached)

    try:
        data = await provider.arender_map(parameters)
    except (ProviderGenericError, ProviderInvalidDataError) as error:
        if not _is_expected(error):
            # Inside the except block pygeoapi logs the traceback, which a
            # server error needs.
            return _answer_error(api, request, headers, error)
        failed = error
    else:
        failed = None
    if failed is not None:
        return _answer_error(api, request, headers, failed)
    if cached:
        # The data may change while the map is drawn. An ETag must name the
        # version the map was drawn from, so a map whose version moved goes
        # without cache headers.
        after = await get_cache_headers(http_cache, provider, dataset, "map", parameters, headers)
        if after.get("ETag") != cached["ETag"]:
            cached = {}

    headers["Content-Crs"] = parameters.crs
    headers["Content-Bbox"] = ",".join(map(str, parameters.bbox))
    datetime_ = format_content_datetime(api.config["resources"][dataset]["extents"])
    if datetime_ is not None:
        headers["Content-Datetime"] = datetime_
    headers["Content-Type"] = media_type
    headers.update(cached)
    return headers, HTTPStatus.OK, data


def _is_expected(error: ProviderGenericError | ProviderInvalidDataError) -> bool:
    """Tell an answer the route expects from a server fault.

    A refused request (4xx), a full queue (503) and a map that took too long
    (504) are part of serving maps, so their answers need no traceback.

    Parameters
    ----------
    error
        The error the provider raised.

    Returns
    -------
    bool
        True for a 4xx, a 503 or a 504; False for any other server error,
        whose answer keeps the traceback in the log.
    """
    status = int(error.http_status_code)
    return status < 500 or status in (HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.GATEWAY_TIMEOUT)


def _answer_error(
    api: API,
    request: APIRequest,
    headers: dict,
    error: ProviderGenericError | ProviderInvalidDataError,
) -> tuple[dict, int, Any]:
    headers["Content-Type"] = FORMAT_TYPES[F_JSON]
    # An error may say when to try again, as a full queue does.
    retry_after = getattr(error, "retry_after", None)
    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)
    return api.get_exception(
        error.http_status_code, headers, request.format, error.ogc_exception_code, error.message
    )
