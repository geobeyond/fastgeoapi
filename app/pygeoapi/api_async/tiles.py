"""Tile data served with ``await`` when the provider is natively async (ADR-0010, decision 5).

Mirrors ``pygeoapi/api/tiles.py::get_collection_tiles_data`` step by
step: same format check, same headers, same 204 on a missing tile, same
404 on ``ProviderTileNotFoundError``, same generic mapping through
``api.get_exception``. The one difference is that the provider is
awaited on the event loop instead of being called in the threadpool.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from pygeoapi import plugin as pygeoapi_plugin
from pygeoapi.api import API, SYSTEM_LOCALE, APIRequest
from pygeoapi.provider import get_provider_by_type
from pygeoapi.provider.base import ProviderGenericError, ProviderTypeError
from pygeoapi.provider.tile import ProviderTileNotFoundError
from pygeoapi.util import filter_dict_by_key_value

from app.interfaces.providers import AsyncTileProvider


def native_tile_provider(api: API, dataset: str) -> tuple[dict, AsyncTileProvider] | None:
    """The collection's tile provider definition and instance, when native async.

    Returns ``None`` for unknown collections, collections without a tile
    provider, providers that fail to build and providers that are not
    native: every one of those keeps pygeoapi's own handler, which
    answers exactly as before. Instantiation goes through
    ``pygeoapi.plugin.load_plugin``, the cached one after
    ``patch_load_plugin``, so a ``THREAD_SAFE`` provider is built once.
    """
    collections = filter_dict_by_key_value(api.config["resources"], "type", "collection")
    if dataset not in collections:
        return None
    try:
        provider_def = get_provider_by_type(api.config["resources"][dataset]["providers"], "tile")
        provider = pygeoapi_plugin.load_plugin("provider", provider_def)
    except (KeyError, ProviderTypeError, ProviderGenericError):
        return None
    if isinstance(provider, AsyncTileProvider) and provider.native_async:
        return provider_def, provider
    return None


async def get_collection_tiles_data(
    api: API,
    request: APIRequest,
    dataset: str,
    matrix_id: str,
    z: str,
    y: str,
    x: str,
    provider_def: dict,
    provider: AsyncTileProvider,
) -> tuple[dict, int, Any]:
    """``(headers, status, content)`` for one tile, awaiting the provider."""
    if not request.format:
        return api.get_format_exception(request)
    headers = request.get_response_headers(SYSTEM_LOCALE, **api.api_headers)
    format_ = provider.format_type
    try:
        headers["Content-Type"] = provider_def["format"]["mimetype"]
        content = await provider.aget_tiles(
            layer=provider.get_layer(), tileset=matrix_id, z=z, y=y, x=x, format_=format_
        )
    except KeyError:
        return api.get_exception(
            HTTPStatus.BAD_REQUEST,
            headers,
            format_,
            "InvalidParameterValue",
            "Invalid collection tiles",
        )
    except ProviderTileNotFoundError:
        return headers, HTTPStatus.NOT_FOUND, "Tile not found"
    except ProviderGenericError as err:
        return api.get_exception(
            err.http_status_code,
            headers,
            request.format,
            err.ogc_exception_code,
            err.message,
        )
    if content is None:
        return api.get_exception(
            HTTPStatus.NO_CONTENT, headers, format_, "NoContent", "identifier not found"
        )
    return headers, HTTPStatus.OK, content
