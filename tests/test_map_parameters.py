"""The map parameters the route checks and normalises before any provider sees them.

``app.*`` is imported at the top of this module, nowhere else.
"""

from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from pygeoapi.api import APIRequest
from starlette.requests import Request

from app.interfaces.providers import MapCapabilities, MapLimits
from app.provider.maps import MapParameterError, MapTooLargeError
from app.pygeoapi.api_async.map_parameters import (
    clip_bbox,
    format_content_datetime,
    parse_map_parameters,
)

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
EDGE = 20037508.342789244
LIMITS = MapLimits(2048, 2048, None, 1, 8, 30.0)
CAPABILITIES = MapCapabilities(crs=(WEB_MERCATOR,), formats=("png",))
EXTENTS = {"spatial": {"bbox": [-180, -90, 180, 90], "crs": CRS84}}


def _parse(limits=LIMITS, **params):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/collections/roads/map",
        "query_string": urlencode(params).encode(),
        "headers": [],
    }
    request = APIRequest(Request(scope), ["en-US"])
    return parse_map_parameters(
        request, {"storage_crs": WEB_MERCATOR}, EXTENTS, limits, CAPABILITIES, None
    )


@pytest.mark.parametrize("value", ["0", "-3", "1.5", "wide"])
def test_width_and_height_must_be_positive_integers(value):
    for name in ("width", "height"):
        with pytest.raises(MapParameterError) as error:
            _parse(**{name: value})
        assert not isinstance(error.value, MapTooLargeError)


def test_a_map_above_a_side_is_too_large():
    with pytest.raises(MapTooLargeError):
        _parse(width=2049)

    assert _parse(width=2048).width == 2048


def test_a_map_above_the_pixels_is_too_large():
    with pytest.raises(MapTooLargeError):
        _parse(MapLimits(2048, 2048, 1_000_000, 1, 8, 30.0), width=1001, height=1000)


def test_without_max_pixels_only_the_sides_count():
    parameters = _parse(width=2048, height=2048)

    assert (parameters.width, parameters.height) == (2048, 2048)


@pytest.mark.parametrize("bbox", ["1,2,3", "a,b,c,d", "nan,0,1,1", "inf,0,1,1"])
def test_a_bbox_needs_four_finite_numbers(bbox):
    with pytest.raises(MapParameterError):
        _parse(bbox=bbox)


def test_a_degenerate_bbox_is_refused():
    with pytest.raises(MapParameterError):
        _parse(bbox="12,41,12,42")


def test_a_bbox_upside_down_is_refused():
    with pytest.raises(MapParameterError):
        _parse(bbox="12,42,13,41")


def test_coordinates_outside_web_mercator_are_clipped():
    assert clip_bbox((-3e7, -1e6, 3e7, 1e6), WEB_MERCATOR) == (-EDGE, -1e6, EDGE, 1e6)
    assert clip_bbox((-1e6, -3e7, 1e6, 3e7), WEB_MERCATOR) == (-1e6, -EDGE, 1e6, EDGE)
    assert clip_bbox((-1e6, float("-inf"), 1e6, float("inf")), WEB_MERCATOR) == (
        -1e6,
        -EDGE,
        1e6,
        EDGE,
    )


def test_a_bbox_entirely_outside_is_nothing_to_draw():
    assert clip_bbox((-1e6, 2.5e7, 1e6, 3e7), WEB_MERCATOR) is None
    assert clip_bbox((2.5e7, -1e6, 3e7, 1e6), WEB_MERCATOR) is None
    assert _parse(bbox="-1000000,25000000,1000000,30000000", **{"bbox-crs": WEB_MERCATOR}) is None


def test_a_crossing_stays_a_crossing():
    clipped = clip_bbox((1.9e7, -1e6, -1.9e7, 1e6), WEB_MERCATOR)

    assert clipped is not None
    assert clipped[0] > clipped[2]


def test_a_bbox_on_the_edges_of_web_mercator_is_kept():
    assert clip_bbox((-EDGE, -EDGE, EDGE, EDGE), WEB_MERCATOR) == (-EDGE, -EDGE, EDGE, EDGE)


def test_a_crs_the_provider_does_not_draw_is_refused():
    with pytest.raises(MapParameterError):
        _parse(crs=CRS84)


def test_the_crs_takes_the_spelling_the_provider_declares():
    assert _parse(crs="EPSG:3857").crs == WEB_MERCATOR
    assert _parse(crs=WEB_MERCATOR.lower()).crs == WEB_MERCATOR


def test_the_canonical_crs84_uri_is_a_valid_bbox_crs():
    parameters = _parse(bbox="12.4,41.8,12.6,42.0", **{"bbox-crs": CRS84})

    assert parameters.crs == WEB_MERCATOR
    assert 1_380_000 < parameters.bbox[0] < 1_381_000


def test_a_bbox_crs_outside_the_published_ones_is_refused():
    with pytest.raises(MapParameterError):
        _parse(bbox="12.4,41.8,12.6,42.0", **{"bbox-crs": "4326"})


def test_a_format_outside_the_capabilities_is_refused():
    with pytest.raises(MapParameterError):
        _parse(f="jpeg")


def test_content_datetime_spans_the_temporal_extent():
    begin, end = "2020-01-01T00:00:00Z", "2021-06-30T12:00:00Z"

    assert format_content_datetime({"temporal": {"begin": begin, "end": None}}) == f"{begin}/.."
    assert format_content_datetime({"temporal": {"begin": None, "end": end}}) == f"../{end}"
    assert format_content_datetime({"temporal": {"begin": begin, "end": end}}) == f"{begin}/{end}"
    assert format_content_datetime({"temporal": {"begin": begin, "end": begin}}) == begin
    parsed = datetime(2020, 1, 1, tzinfo=UTC)
    assert format_content_datetime({"temporal": {"begin": parsed, "end": None}}) == f"{begin}/.."


def test_a_collection_without_time_has_no_content_datetime():
    assert format_content_datetime(EXTENTS) is None
    assert format_content_datetime({**EXTENTS, "temporal": {"begin": None, "end": None}}) is None
