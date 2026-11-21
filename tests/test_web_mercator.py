"""The bounds of Web Mercator, and how a bbox is held within them.

``app.*`` is imported at the top of this module, nowhere else.
"""

import math

import pytest

from app.interfaces.ogc import OGC_CRS_WEB_MERCATOR
from app.maps.web_mercator import (
    WEB_MERCATOR_EDGE,
    WEB_MERCATOR_MAX_LATITUDE,
    clip_web_mercator_bbox,
    is_outside_web_mercator,
)

EDGE = 20037508.342789244


def test_web_mercator_is_named_by_its_ogc_uri():
    assert OGC_CRS_WEB_MERCATOR == "http://www.opengis.net/def/crs/EPSG/0/3857"


def test_the_edge_is_half_the_circumference_of_the_sphere():
    assert WEB_MERCATOR_EDGE == pytest.approx(math.pi * 6378137, abs=1e-6)
    assert WEB_MERCATOR_EDGE == EDGE


def test_the_max_latitude_is_where_y_reaches_the_edge():
    assert WEB_MERCATOR_MAX_LATITUDE == pytest.approx(85.0511287798, abs=1e-10)


@pytest.mark.parametrize(
    "bbox",
    [
        (-1e6, 2.5e7, 1e6, 3e7),
        (-1e6, -3e7, 1e6, -2.5e7),
        (2.5e7, -1e6, 3e7, 1e6),
        (-3e7, -1e6, -2.5e7, 1e6),
        (2.5e7, -1e6, -2.5e7, 1e6),
    ],
)
def test_a_bbox_entirely_beyond_an_edge_lies_outside(bbox):
    assert is_outside_web_mercator(bbox)


@pytest.mark.parametrize(
    "bbox",
    [
        (-1e6, -1e6, 1e6, 1e6),
        (-3e7, -1e6, 3e7, 1e6),
        (1.9e7, -1e6, -1.9e7, 1e6),
        (-EDGE, -EDGE, EDGE, EDGE),
    ],
)
def test_a_bbox_that_touches_the_world_does_not_lie_outside(bbox):
    assert not is_outside_web_mercator(bbox)


def test_coordinates_beyond_the_edges_are_moved_onto_them():
    assert clip_web_mercator_bbox((-3e7, -1e6, 3e7, 1e6)) == (-EDGE, -1e6, EDGE, 1e6)
    assert clip_web_mercator_bbox((-1e6, -3e7, 1e6, 3e7)) == (-1e6, -EDGE, 1e6, EDGE)
    assert clip_web_mercator_bbox((-1e6, float("-inf"), 1e6, float("inf"))) == (
        -1e6,
        -EDGE,
        1e6,
        EDGE,
    )


def test_a_crossing_stays_a_crossing():
    clipped = clip_web_mercator_bbox((1.9e7, -1e6, -1.9e7, 1e6))

    assert clipped[0] > clipped[2]


def test_a_bbox_on_the_edges_is_kept():
    assert clip_web_mercator_bbox((-EDGE, -EDGE, EDGE, EDGE)) == (-EDGE, -EDGE, EDGE, EDGE)
