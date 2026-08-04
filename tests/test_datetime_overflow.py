"""Regression: giant datetime values must be a 400, not a crash.

Found by schemathesis 4.24 fuzzing (fuzz dictionaries now reach
parameters behind ``$ref``): ``datetime=999999999999999999999999999999``
raises ``OverflowError: Python int too large to convert to C long``
inside ``dateutil.parser.parse``. pygeoapi's ``validate_datetime`` and
its callers only catch ``ValueError`` — dateutil documents that its
parser raises ``OverflowError`` too — so the request crashes with a 500
instead of the invalid-parameter 400. Patched locally in
``app/pygeoapi/patches.py`` until fixed upstream.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

GIANT = "999999999999999999999999999999"


@pytest.mark.parametrize(
    "datetime_value",
    [
        GIANT,
        f"2003-10-30/{GIANT}",
        f"{GIANT}/..",
    ],
)
def test_giant_datetime_is_client_error(unprotected_app, datetime_value):
    """An out-of-range datetime is the client's fault: 400, never 500."""
    client = TestClient(unprotected_app, raise_server_exceptions=False)
    response = client.get(
        "/geoapi/collections/obs/items",
        params={"datetime": datetime_value, "f": "json"},
    )
    assert response.status_code == 400, (
        f"expected 400 for datetime={datetime_value}, "
        f"got {response.status_code}: {response.text[:200]}"
    )


def test_valid_datetime_still_works(unprotected_app):
    """The overflow guard must not break legitimate temporal queries."""
    client = TestClient(unprotected_app, raise_server_exceptions=False)
    response = client.get(
        "/geoapi/collections/obs/items",
        params={"datetime": "2003-10-30/2003-10-31", "f": "json"},
    )
    assert response.status_code == 200, response.text[:200]
