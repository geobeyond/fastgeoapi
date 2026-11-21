"""The map route of the native map providers.

It checks the parameters with :mod:`.map_parameters`, awaits the provider
on the event loop, and answers with the statuses and headers of
``pygeoapi/api/maps.py::get_collection_map``.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, Any, assert_never

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

from app.interfaces.providers import AsyncMapProvider, MapFormat, NotRenderedMap, RenderedMap
from app.provider.maps import MapParameterError
from app.pygeoapi.api_async.caching import (
    HttpCache,
    answer_not_modified,
    build_cache_headers,
    get_cache_headers,
    is_not_modified,
)
from app.pygeoapi.api_async.map_parameters import format_content_datetime, parse_map_parameters
from app.pygeoapi.map_limits import clamp_provider_map_limits, get_server_map_limits

if TYPE_CHECKING:
    from app.config.app import DevConfig, ProdConfig


def find_native_map_provider(api: API, dataset: str) -> tuple[dict, AsyncMapProvider] | None:
    """Find the native map provider of a collection.

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
    settings: DevConfig | ProdConfig | None = None,
) -> tuple[dict, int, Any]:
    """Answer one map request, awaiting the provider.

    With a cache policy, a provider that knows its version gives the map an
    ``ETag``, and a request that names it gets a 304 without a draw. A drawn
    map gets the ``ETag`` of the version the provider drew it from. The map
    is held to the smaller of the server's limits and the provider's.

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
        The cache policy, or None for no cache headers.
    settings
        fastgeoapi's settings, which hold the server's map limits; None
        takes those of the running server, or their defaults when they
        cannot be built.

    Returns
    -------
    tuple of (dict, int, Any)
        The headers, the status and the content: 400 for a parameter the
        route cannot read or the provider does not draw, 404 for a style the
        provider does not declare, 413 above the limits, 204 for a bbox
        entirely outside the CRS of the map, and the status of a map the
        provider cannot draw now.
    """
    headers = request.get_response_headers(**api.api_headers)
    limits = clamp_provider_map_limits(provider.limits, *get_server_map_limits(settings))
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
        drawn = await provider.arender_map(parameters)
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
    match drawn:
        case NotRenderedMap():
            return _answer_not_rendered(api, request, headers, drawn)
        case RenderedMap():
            pass
        case _:
            assert_never(drawn)

    headers["Content-Crs"] = parameters.crs
    headers["Content-Bbox"] = ",".join(map(str, parameters.bbox))
    datetime_ = format_content_datetime(api.config["resources"][dataset]["extents"])
    if datetime_ is not None:
        headers["Content-Datetime"] = datetime_
    headers["Content-Type"] = media_type
    headers.update(
        build_cache_headers(http_cache, drawn.version, dataset, "map", parameters, headers)
    )
    return headers, HTTPStatus.OK, drawn.content


def _is_expected(error: ProviderGenericError | ProviderInvalidDataError) -> bool:
    """Tell an answer the route expects from a server fault.

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
    return api.get_exception(
        error.http_status_code, headers, request.format, error.ogc_exception_code, error.message
    )


def _answer_not_rendered(
    api: API,
    request: APIRequest,
    headers: dict,
    not_rendered: NotRenderedMap,
) -> tuple[dict, int, Any]:
    headers["Content-Type"] = FORMAT_TYPES[F_JSON]
    if not_rendered.retry_after is not None:
        headers["Retry-After"] = str(not_rendered.retry_after)
    return api.get_exception(
        not_rendered.status,
        headers,
        request.format,
        ProviderGenericError.ogc_exception_code,
        not_rendered.message,
    )
