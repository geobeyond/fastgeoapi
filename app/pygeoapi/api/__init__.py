"""API package for patched pygeoapi.

Mirrors upstream's ``pygeoapi/api`` package: overrides and runtime
patches for a given upstream module live in the same-named module here
(``pygeoapi/api/__init__.py`` → this file, ``pygeoapi/api/...`` →
sibling modules such as ``conformance.py`` and ``processes.py``).
"""

from __future__ import annotations

import functools

import pygeoapi.api
import pygeoapi.api.environmental_data_retrieval
import pygeoapi.api.itemtypes
import pygeoapi.api.maps

_UPSTREAM_VALIDATE_DATETIME = pygeoapi.api.validate_datetime


@functools.wraps(_UPSTREAM_VALIDATE_DATETIME)
def validate_datetime(resource_def, datetime_=None):
    """Overflow-safe wrapper of upstream ``pygeoapi.api.validate_datetime``.

    ``dateutil.parser.parse`` documents raising ``OverflowError`` (e.g.
    ``datetime=999999999999999999999999999999``, found by schemathesis
    fuzzing), but pygeoapi's callers only catch ``ValueError`` — the
    overflow escapes as a 500 instead of the invalid-parameter 400.
    Remove once fixed upstream in pygeoapi.
    """
    try:
        return _UPSTREAM_VALIDATE_DATETIME(resource_def, datetime_)
    except OverflowError as err:
        raise ValueError(f"datetime value out of range: {err}") from err


def patch_validate_datetime_overflow() -> None:
    """Rebind the overflow-safe wrapper everywhere upstream imported it.

    pygeoapi consumers use ``from . import validate_datetime``, so the
    symbol must be replaced in each consumer module, not just in
    ``pygeoapi.api``. Idempotent: re-applying is a no-op.
    """
    for module in (
        pygeoapi.api,
        pygeoapi.api.itemtypes,
        pygeoapi.api.maps,
        pygeoapi.api.environmental_data_retrieval,
    ):
        if module.validate_datetime is not validate_datetime:
            module.validate_datetime = validate_datetime  # ty: ignore[invalid-assignment]
