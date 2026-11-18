"""Override module for pygeoapi's items endpoint.

OGC API - Features Part 3 lets ``filter`` carry CQL2 JSON when
``filter-lang`` is ``cql2-json`` (/req/filter/filter-lang-param). pygeoapi
0.24 reads ``filter`` as CQL2 text whatever ``filter-lang`` says, and reads
CQL2 JSON only from the body of the request (``api/itemtypes.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygeoapi.api.itemtypes
from starlette.datastructures import QueryParams

if TYPE_CHECKING:
    from pygeoapi.api import API, APIRequest


def move_json_filter_to_body(request: APIRequest) -> None:
    """Move a CQL2 JSON ``filter`` from the query to the body of a request.

    When ``filter-lang`` is ``cql2-json`` and ``filter`` is given, the body
    becomes the UTF-8 bytes of ``filter`` and the query keeps every other
    parameter, ``filter-lang`` and ``filter-crs`` included. Any other request
    is left unchanged.

    Parameters
    ----------
    request
        The pygeoapi request of a ``GET`` on the items, changed in place.
    """
    params = request.params
    expression = params.get("filter")
    if params.get("filter-lang") != "cql2-json" or expression is None:
        return
    # APIRequest has no setter for either: these are the attributes behind
    # its `data` and `params` properties.
    request._data = expression.encode()
    request._args = QueryParams(
        [(key, value) for key, value in params.multi_items() if key != "filter"]
    )


def get_collection_items(api: API, request: APIRequest, dataset: str) -> tuple[dict, int, str]:
    """Get the items of a collection, with ``filter`` in CQL2 text or CQL2 JSON.

    The answer is pygeoapi's ``get_collection_items`` for the request after
    :func:`move_json_filter_to_body`.

    Parameters
    ----------
    api
        The pygeoapi API instance.
    request
        The request of a ``GET`` on the items of ``dataset``; its ``filter``
        is read according to ``filter-lang`` (/req/filter/filter-param,
        /req/filter/filter-lang-param).
    dataset
        The id of the collection.

    Returns
    -------
    tuple[dict, int, str]
        The headers, the status and the content pygeoapi answers with.
    """
    move_json_filter_to_body(request)
    return pygeoapi.api.itemtypes.get_collection_items(api, request, dataset)
