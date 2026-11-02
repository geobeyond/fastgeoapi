"""What the route answers for a map of each provider, whatever the engine."""

import pytest

from tests.maps_fixtures import FakeRenderer

MAP = "/collections/under_test/map"


def test_an_unknown_style_answers_404(contract):
    response = contract.client.get("/collections/under_test/styles/unknown/map")

    assert response.status_code == 404, response.text[:200]


@pytest.mark.parametrize(
    ("params", "status"),
    [
        ({"width": 1025}, 413),
        ({"width": 5}, 200),
        ({"width": 0}, 400),
        ({"bbox": "10,10,10,20", "bbox-crs": "http://www.opengis.net/def/crs/EPSG/0/3857"}, 400),
    ],
    ids=["above-max-size", "small", "zero-width", "degenerate-bbox"],
)
def test_the_status_of_a_map(contract, params, status):
    response = contract.client.get(MAP, params=params)

    assert response.status_code == status, response.text[:200]


@pytest.mark.parametrize(("text", "value"), [("false", False), ("true", True)])
def test_transparent_reaches_the_engine_as_a_boolean(contract, text, value):
    response = contract.client.get(MAP, params={"transparent": text, "width": 16, "height": 16})

    assert response.status_code == 200, response.text[:200]
    if contract.records_requests:
        assert FakeRenderer.instances[-1].requests[-1].transparent is value
