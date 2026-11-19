"""Override module for pygeoapi's items endpoint.

OGC API - Features Part 3 lets ``filter`` carry CQL2 JSON when
``filter-lang`` is ``cql2-json`` (/req/filter/filter-lang-param), and asks
for a 400 when the value of ``filter`` is invalid
(/req/features-filter/response). pygeoapi 0.24 reads ``filter`` as CQL2 text
whatever ``filter-lang`` says, reads CQL2 JSON only from the body of the
request, and passes on any JSON its parser accepts, such as a number or a
property name alone (``api/itemtypes.py``). It also builds the links of the
answer from the query alone, so the ``next`` link of a ``POST`` drops the
filter of its body.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

import pygeoapi.api.itemtypes
from pygeoapi.api import SYSTEM_LOCALE
from pygeofilter import ast
from pygeofilter.parsers.cql2_json import parse as parse_cql2_json
from starlette.datastructures import QueryParams

if TYPE_CHECKING:
    from pygeoapi.api import API, APIRequest


class QueryWithJsonFilter(QueryParams):
    """The query of a request whose CQL2 JSON ``filter`` is also its body.

    ``get("filter")`` gives the default, so pygeoapi reads the filter from
    the body. Every other access, iteration included, sees ``filter`` as
    given, so the links pygeoapi builds from the query keep it.
    """

    def get(self, key: Any, default: Any = None) -> Any:
        """Get the value of ``key``, or ``default`` for ``filter``.

        Parameters
        ----------
        key
            The name of the query parameter.
        default
            The value when ``key`` is absent or is ``filter``.

        Returns
        -------
        Any
            The last value of ``key`` in the query, or ``default``.
        """
        if key == "filter":
            return default
        return super().get(key, default)


def move_json_filter_to_body(request: APIRequest) -> None:
    """Make a CQL2 JSON ``filter`` the body of a request.

    When ``filter-lang`` is ``cql2-json`` and ``filter`` is given, the body
    becomes the UTF-8 bytes of ``filter`` and the query becomes a
    :class:`QueryWithJsonFilter`. Any other request is left unchanged.

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
    request._args = QueryWithJsonFilter(list(params.multi_items()))


def copy_json_body_to_query(request: APIRequest) -> None:
    """Put the CQL2 JSON body of a request in its query too.

    pygeoapi builds the links of the answer from the query, so a filter
    that lives only in the body drops out of ``next``. For a ``POST`` with
    ``?f=json&limit=1`` and the body
    ``{"op": "<>", "args": [{"property": "name"}, "gamma"]}``, the query
    becomes::

        f=json&limit=1&filter={"op":"<>",...}&filter-lang=cql2-json

    The query is a :class:`QueryWithJsonFilter`, so pygeoapi asking for
    ``filter`` still gets nothing and reads the body, while the links it
    builds from every parameter carry the filter as a ``GET``. A
    ``filter-lang`` already in the query is replaced, and a query that
    already has ``filter``, as after :func:`move_json_filter_to_body`, is
    left unchanged.

    Parameters
    ----------
    request
        The pygeoapi request of a ``POST`` on the items, with a body that
        is a valid CQL2 JSON filter, changed in place.
    """
    params = request.params
    if "filter" in params:
        return
    expression = json.dumps(json.loads(request.data), separators=(",", ":"))
    items = [(key, value) for key, value in params.multi_items() if key != "filter-lang"]
    request._args = QueryWithJsonFilter(
        [*items, ("filter", expression), ("filter-lang", "cql2-json")]
    )


def validate_json_or_problem(expression: bytes) -> str | None:
    """Validate a CQL2 JSON filter, or give the reason it is invalid.

    Parameters
    ----------
    expression
        The CQL2 JSON filter, as the bytes of the body.

    Returns
    -------
    str or None
        The reason for the 400 answer, or ``None`` when ``expression`` is a
        boolean expression: a comparison, spatial, temporal or array
        predicate, ``and``, ``or``, ``not``, or ``true`` and ``false``
        (/req/features-filter/response).
    """
    try:
        node = parse_cql2_json(expression.decode())
    except Exception:
        # The parser raises whatever the input leads it to, a RecursionError
        # included; every one of them means the filter is not CQL2 JSON.
        return "Bad CQL JSON"
    if isinstance(node, (ast.Condition, ast.Predicate, bool)):
        return None
    return "The CQL2 JSON filter is not a boolean expression"


def get_collection_items(
    api: API, request: APIRequest, dataset: str
) -> tuple[dict, int, str | bytes]:
    """Get the items of a collection, with ``filter`` in CQL2 text or CQL2 JSON.

    A CQL2 JSON filter, given in ``filter`` or as the body, must be a
    boolean expression; any other filter is answered with 400 and the code
    ``InvalidParameterValue``. Otherwise the answer is pygeoapi's
    ``get_collection_items`` for the request after
    :func:`move_json_filter_to_body`, and for a body after
    :func:`copy_json_body_to_query`.

    Parameters
    ----------
    api
        The pygeoapi API instance.
    request
        The request on the items of ``dataset``: a ``GET``, or a ``POST``
        with a CQL2 JSON body. Its ``filter`` is read according to
        ``filter-lang`` (/req/filter/filter-param,
        /req/filter/filter-lang-param).
    dataset
        The id of the collection.

    Returns
    -------
    tuple[dict, int, str or bytes]
        The headers, the status and the content of the answer: bytes for a
        binary format such as CSV.
    """
    move_json_filter_to_body(request)
    if request.data and request.params.get("filter") is None:
        problem = validate_json_or_problem(request.data)
        if problem is not None:
            headers = request.get_response_headers(SYSTEM_LOCALE, **api.api_headers)
            return api.get_exception(
                HTTPStatus.BAD_REQUEST, headers, request.format, "InvalidParameterValue", problem
            )
        copy_json_body_to_query(request)
    return pygeoapi.api.itemtypes.get_collection_items(api, request, dataset)
