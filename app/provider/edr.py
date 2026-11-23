"""The errors of an EDR query, which pygeoapi turns into HTTP answers."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from pygeoapi.provider.base import ProviderGenericError


class _EdrError(ProviderGenericError):
    """An EDR error whose message, when none is given, is its ``default_msg``.

    pygeoapi's errors pass ``msg`` on to the exception, so one raised
    without a message logs as ``None``.
    """

    def __init__(self, msg: str | None = None, *args: Any, user_msg: str | None = None) -> None:
        super().__init__(msg or user_msg or self.default_msg, *args, user_msg=user_msg)


class EdrParameterError(_EdrError):
    """An EDR query parameter this server cannot honour."""

    ogc_exception_code = "InvalidParameterValue"
    http_status_code = HTTPStatus.BAD_REQUEST
    default_msg = "invalid EDR parameter"


class EdrNotAcceptableError(EdrParameterError):
    """An ``Accept`` that names no format the collection answers in and no wildcard.

    Content negotiation failed: OGC API - Common - Part 1 answers it with
    406, where a wrong ``f`` is a 400.
    """

    ogc_exception_code = "NoApplicableCode"
    http_status_code = HTTPStatus.NOT_ACCEPTABLE
    default_msg = "no format the data is returned in is acceptable"


class EdrQueryNotOfferedError(EdrParameterError):
    """A query type the collection does not offer."""

    ogc_exception_code = "NotFound"
    http_status_code = HTTPStatus.NOT_FOUND
    default_msg = "query type not offered by this collection"


class EdrTooLargeError(EdrParameterError):
    """A query that would return more values than the server allows."""

    http_status_code = HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    default_msg = "the query returns more values than this server allows"
