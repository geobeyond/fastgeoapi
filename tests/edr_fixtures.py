"""A native EDR provider over a tiny in-memory grid, for the tests of the route."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any, ClassVar

from pygeoapi.provider.base import BaseProvider

from app.interfaces.providers import (
    AreaQuery,
    DataTooLarge,
    EdrCapabilities,
    EdrFormat,
    EdrLimits,
    EdrParameter,
    NoDataFound,
    NotRetrievedData,
    PositionQuery,
    RetrievedData,
)

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
GRID = {"t2m": [[280.0, 281.0], [282.0, 283.0]]}
"""The values by parameter on a grid of two by two cells."""


class FakeEdrProvider(BaseProvider):
    """A native EDR provider that answers from ``GRID``.

    The ``options`` of its definition steer it.

    Attributes
    ----------
    queries
        Every query ``aretrieve_data`` received, newest last, shared by all
        instances.

    Notes
    -----
    ``version`` is the version of the data, ``"v1"`` by default.
    ``fail`` is ``"busy"`` or ``"timeout"`` for a ``NotRetrievedData`` with
    status 503 or 504, and ``"no_data"`` for ``NoDataFound``.
    ``retry_after`` goes with ``busy``. ``extra_headers`` are returned with
    the data, and ``max_values`` is the provider's own limit. A value
    counts once per parameter and per place, or per cell of the grid for an
    area.
    """

    native_async: ClassVar[bool] = True
    queries: ClassVar[list] = []

    def __init__(self, provider_def: dict) -> None:
        super().__init__(provider_def)
        self.options = provider_def.get("options") or {}

    @property
    def limits(self) -> EdrLimits:
        return EdrLimits(max_values=self.options.get("max_values"))

    @property
    def capabilities(self) -> EdrCapabilities:
        return EdrCapabilities(
            query_types=("position", "area"),
            crs=(CRS84,),
            default_crs=CRS84,
            formats=(EdrFormat.COVERAGEJSON,),
            parameters=(EdrParameter("t2m", "Temperature", "K"),),
        )

    async def aretrieve_data(self, query):
        FakeEdrProvider.queries.append(query)
        count = self._count_values(query)
        if count > query.max_values:
            return DataTooLarge(values=count, limit=query.max_values)
        match self.options.get("fail"):
            case "busy":
                return NotRetrievedData(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "the store is busy",
                    self.options.get("retry_after"),
                )
            case "timeout":
                return NotRetrievedData(HTTPStatus.GATEWAY_TIMEOUT, "the read timed out", None)
            case "no_data":
                return NoDataFound()
        body = {"type": "Coverage", "values": count}
        return RetrievedData(
            content=json.dumps(body).encode(),
            version=self.options.get("version", "v1"),
            extra_headers=self.options.get("extra_headers") or {},
        )

    async def aget_version(self, query) -> str | None:
        return self.options.get("version", "v1")

    def close(self) -> None:
        """Nothing to release."""

    def get_query_types(self) -> list[str]:
        return ["position", "area"]

    def get_fields(self) -> dict[str, Any]:
        return {"t2m": {"type": "number", "title": "Temperature", "x-ogc-unit": "K"}}

    @staticmethod
    def _count_values(query) -> int:
        parameters = len(query.parameter_names) or len(GRID)
        match query:
            case PositionQuery():
                places = len(getattr(query.coords, "geoms", [query.coords]))
            case AreaQuery():
                places = 4
            case _:
                places = 1
        return parameters * places


class ThreadedEdrProvider(FakeEdrProvider):
    """The same provider, which pygeoapi serves in its threadpool."""

    native_async = False

    def query(self, **kwargs):
        return {"type": "Coverage", "served": "pygeoapi"}


def edr_provider(**options: Any) -> dict:
    """Build the definition of a ``FakeEdrProvider`` with the given options.

    Parameters
    ----------
    **options
        The options of the provider: ``version``, ``fail``, ``retry_after``,
        ``extra_headers`` and ``max_values``.

    Returns
    -------
    dict
        The provider definition, ready for a collection's ``providers``.
    """
    return {
        "type": "edr",
        "name": "tests.edr_fixtures.FakeEdrProvider",
        "data": "unused",
        "options": options,
    }
