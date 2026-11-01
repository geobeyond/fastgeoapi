"""Validate the JSON fastgeoapi returns against the official OGC schemas."""

from typing import Any

import pytest

from tests.conformance.conftest import Served

validate_response = pytest.importorskip("xpublish_ogc_core.testing").validate_response


def get_json(served: Served, path: str) -> tuple[int, Any]:
    """Request the JSON representation of a path.

    Parameters
    ----------
    served
        The configuration to ask.
    path
        The path under the sub-app, without the ``f`` parameter.

    Returns
    -------
    tuple[int, Any]
        The status code and the decoded body.
    """
    response = served.client.get(path, params={"f": "json"})
    return response.status_code, response.json()


def test_the_landing_page_follows_ogc_common(served: Served) -> None:
    """The landing page is a Common Part 1 ``landingPage``."""
    status, body = get_json(served, "/")

    assert status == 200
    validate_response("landingPage", body, document="common")
