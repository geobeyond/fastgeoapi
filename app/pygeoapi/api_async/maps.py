"""Maps served with ``await`` when the provider is natively async.

The route answers what ``pygeoapi/api/maps.py::get_collection_map``
answers, with the same headers, and differs in three ways. The provider
is awaited on the event loop instead of being called in the threadpool.
The parameters are checked once, by :mod:`.map_parameters`, before the
provider is called. And the provider gets the contract's arguments only:
the route moves the bbox into ``crs`` and keeps ``bbox-crs`` for itself.
"""

from __future__ import annotations

from dataclasses import asdict
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

from app.interfaces.providers import AsyncMapProvider
from app.provider.maps import MapParameterError
from app.pygeoapi.api_async.admission import admission_for
from app.pygeoapi.api_async.caching import (
    HttpCache,
    cache_headers,
    not_modified,
    not_modified_answer,
)
from app.pygeoapi.api_async.map_parameters import format_content_datetime, parse_map_parameters
from app.pygeoapi.map_limits import MapCeiling, collection_limits, default_map_ceiling


def native_map_provider(api: API, dataset: str) -> tuple[dict, AsyncMapProvider] | None:
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
        the map being drawn.
    map_ceiling
        The server's ceiling on map sizes; None takes the one of the
        settings. The map is held to the smaller of it and the provider's
        limits.

    Returns
    -------
    tuple of (dict, int, Any)
        The headers, the status and the content: 400 for a parameter the
        route cannot read or the provider does not draw, 413 above the
        limits, 204 for a bbox entirely outside the CRS of the map, 503
        when the provider's slots are all taken, 504 past its timeout.
    """
    headers = request.get_response_headers(**api.api_headers)
    ceiling = map_ceiling if map_ceiling is not None else default_map_ceiling()
    limits = collection_limits(provider.limits, ceiling)
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
        return _error(api, request, headers, error)
    if parameters is None:
        return headers, HTTPStatus.NO_CONTENT, b""
    arguments = asdict(parameters)

    cached = await cache_headers(http_cache, provider, dataset, "map", arguments, headers)
    asked = get_from_headers(request.headers, "if-none-match")
    if cached and not_modified(asked, cached["ETag"]):
        headers["Content-Type"] = collection_def["format"]["mimetype"]
        return not_modified_answer(headers, cached)

    try:
        data = await admission_for(provider, limits).run(lambda: provider.arender_map(**arguments))
    except (ProviderGenericError, ProviderInvalidDataError) as error:
        return _error(api, request, headers, error)

    headers["Content-Crs"] = parameters.crs
    headers["Content-Bbox"] = ",".join(map(str, parameters.bbox))
    datetime_ = format_content_datetime(api.config["resources"][dataset]["extents"])
    if datetime_ is not None:
        headers["Content-Datetime"] = datetime_
    headers["Content-Type"] = collection_def["format"]["mimetype"]
    headers.update(cached)
    return headers, HTTPStatus.OK, data


def _error(
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
