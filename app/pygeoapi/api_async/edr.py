"""The EDR route of the native EDR providers.

It checks the parameters with :mod:`.edr_parameters`, awaits the provider on
the event loop, and answers with the statuses and headers of
``pygeoapi/api/environmental_data_retrieval.py::get_collection_edr_query``.
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

from app.config.logging import create_logger
from app.interfaces.providers import (
    AsyncEdrProvider,
    DataTooLarge,
    EdrFormat,
    EdrQuery,
    NoDataFound,
    NotRetrievedData,
    RetrievedData,
)
from app.provider.edr import EdrParameterError, EdrTooLargeError
from app.pygeoapi.api_async.caching import (
    HttpCache,
    answer_not_modified,
    build_cache_headers,
    is_not_modified,
)
from app.pygeoapi.api_async.edr_parameters import (
    EdrOutsideExtent,
    describe_edr_query,
    parse_edr_query,
)
from app.pygeoapi.api_async.maps import RESERVED_MAP_HEADERS
from app.pygeoapi.edr_limits import clamp_edr_limit, get_server_edr_limit

if TYPE_CHECKING:
    from collections.abc import Mapping

    from app.config.app import DevConfig, ProdConfig

logger = create_logger("app.pygeoapi.api_async.edr")


def find_native_edr_provider(api: API, dataset: str) -> AsyncEdrProvider | None:
    """Find the native EDR provider of a collection.

    Parameters
    ----------
    api
        pygeoapi's API instance.
    dataset
        The collection's name.

    Returns
    -------
    AsyncEdrProvider or None
        The provider. None when the collection does not exist, or its EDR
        provider does not load or is not native; pygeoapi's route then
        serves the query.
    """
    collections = filter_dict_by_key_value(api.config["resources"], "type", "collection")
    if dataset not in collections:
        return None
    try:
        provider_def = get_provider_by_type(api.config["resources"][dataset]["providers"], "edr")
        provider = pygeoapi_plugin.load_plugin("provider", provider_def)
    except (KeyError, ProviderTypeError, ProviderGenericError):
        return None
    if isinstance(provider, AsyncEdrProvider) and provider.native_async:
        return provider
    return None


async def get_collection_edr_query(
    api: API,
    request: APIRequest,
    dataset: str,
    query_type: str,
    provider: AsyncEdrProvider,
    http_cache: HttpCache | None = None,
    settings: DevConfig | ProdConfig | None = None,
) -> tuple[dict, int, Any]:
    """Answer one EDR query, awaiting the provider.

    With a cache policy, a provider that knows its version gives the data
    an ``ETag``, and a request that names it gets a 304 without a read. The
    data gets the ``ETag`` of the version the provider read it from. The
    answer is held to the smaller of the server's limit and the provider's.

    Parameters
    ----------
    api
        pygeoapi's API instance.
    request
        The request.
    dataset
        The collection's name.
    query_type
        The query type of the path, such as ``position``.
    provider
        The collection's EDR provider.
    http_cache
        The cache policy, or None for no cache headers.
    settings
        fastgeoapi's settings, which hold the server's limit; None takes
        those of the running server, or their defaults when they cannot be
        built.

    Returns
    -------
    tuple of (dict, int, Any)
        The headers, the status and the content: 400 for a parameter the
        route cannot read or the provider does not offer, 404 for a query
        type the collection does not offer, 406 for an ``Accept`` it cannot
        meet, 413 above the limit, 204 for a place outside the extent or
        without data, and the status of data the provider cannot read now.
    """
    headers = request.get_response_headers(**api.api_headers)
    limit = clamp_edr_limit(provider.limits, get_server_edr_limit(settings))
    try:
        query = parse_edr_query(
            request,
            api.config["resources"][dataset],
            query_type,
            provider.capabilities,
            limit,
        )
    except EdrParameterError as error:
        refused = error
    else:
        refused = None
    # Answered outside the except block: pygeoapi logs the exception being
    # handled with its traceback, and a refused query is not a server error.
    if refused is not None:
        return _answer_error(api, request, headers, refused)
    match query:
        case EdrOutsideExtent():
            return headers, HTTPStatus.NO_CONTENT, b""
        case _:
            pass

    cached = await _get_cache_headers(http_cache, provider, dataset, query, headers)
    asked = get_from_headers(request.headers, "if-none-match")
    media_type = EdrFormat(query.format_).media_type
    if cached and is_not_modified(asked, cached["ETag"]):
        headers["Content-Type"] = media_type
        return answer_not_modified(headers, cached)

    try:
        retrieved = await provider.aretrieve_data(query)
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
    match retrieved:
        case NoDataFound():
            return headers, HTTPStatus.NO_CONTENT, b""
        case NotRetrievedData():
            return _answer_not_retrieved(api, request, headers, retrieved)
        case DataTooLarge():
            return _answer_error(api, request, headers, _describe_too_large(retrieved))
        case RetrievedData():
            pass
        case _:
            assert_never(retrieved)

    headers["Content-Crs"] = query.crs
    headers["Content-Type"] = media_type
    headers.update(
        build_cache_headers(
            http_cache, retrieved.version, dataset, "edr", describe_edr_query(query), headers
        )
    )
    add_extra_headers(headers, retrieved.extra_headers, dataset)
    return headers, HTTPStatus.OK, retrieved.content


def add_extra_headers(headers: dict, extra_headers: Mapping[str, str], dataset: str) -> None:
    """Add the extra headers of a provider to the headers of its answer.

    A header the route has already set keeps the route's value, and a name
    that describes the body or its caching is dropped; both are logged as a
    warning.

    Parameters
    ----------
    headers
        The headers of the response, completed by the route; changed in
        place.
    extra_headers
        The extra headers of the retrieved data.
    dataset
        The collection's name, for the warning.
    """
    taken = {name.lower() for name in headers}
    for name, value in extra_headers.items():
        lowered = name.lower()
        if lowered in RESERVED_MAP_HEADERS or lowered in taken:
            logger.warning(f"the EDR provider of {dataset} cannot set the {name} header")
            continue
        headers[name] = value


async def _get_cache_headers(
    http_cache: HttpCache | None,
    provider: AsyncEdrProvider,
    dataset: str,
    query: EdrQuery,
    response_headers: dict,
) -> dict[str, str]:
    """Build the cache headers of the answer to ``query``; empty when it gets none.

    Parameters
    ----------
    http_cache
        The cache policy, or None for no cache headers.
    provider
        The provider that answers the query.
    dataset
        The collection's name.
    query
        The checked query.
    response_headers
        The headers of the response so far.

    Returns
    -------
    dict of str to str
        The ``ETag``, ``Cache-Control`` and ``Vary`` headers, or an empty
        dict. A provider error gives none, and the data call reports it;
        any other failure is logged and the query goes on without them.
    """
    if http_cache is None or not http_cache.enabled:
        return {}
    try:
        version = await provider.aget_version(query)
    except ProviderGenericError:
        return {}
    except Exception as error:
        logger.warning(f"the version of an EDR query on {dataset} could not be read: {error!r}")
        return {}
    return build_cache_headers(
        http_cache, version, dataset, "edr", describe_edr_query(query), response_headers
    )


def _describe_too_large(too_large: DataTooLarge) -> EdrTooLargeError:
    return EdrTooLargeError(
        user_msg=(
            f"the query returns {too_large.values} values, "
            f"above the limit of {too_large.limit} values"
        )
    )


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


def _answer_not_retrieved(
    api: API,
    request: APIRequest,
    headers: dict,
    not_retrieved: NotRetrievedData,
) -> tuple[dict, int, Any]:
    headers["Content-Type"] = FORMAT_TYPES[F_JSON]
    if not_retrieved.retry_after is not None:
        headers["Retry-After"] = str(not_retrieved.retry_after)
    return api.get_exception(
        not_retrieved.status,
        headers,
        request.format,
        ProviderGenericError.ogc_exception_code,
        not_retrieved.message,
    )
