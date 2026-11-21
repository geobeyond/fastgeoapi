"""The map parameters the route checks and normalises before any provider sees them.

``app.*`` is imported at the top of this module, nowhere else.
"""

from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from pygeoapi.api import APIRequest
from starlette.requests import Request

from app.interfaces.providers import MapCapabilities, MapLimits
from app.provider.maps import (
    MapNotAcceptableError,
    MapParameterError,
    MapStyleNotFoundError,
    MapTooLargeError,
)
from app.pygeoapi.api_async.map_parameters import (
    MapOutsideCrs,
    format_content_datetime,
    parse_map_parameters,
)
from app.schemas.temporal import TimeInterval

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
LIMITS = MapLimits(2048, 2048, None)
CAPABILITIES = MapCapabilities(
    crs=(WEB_MERCATOR,), default_crs=WEB_MERCATOR, formats=("png",), styles=("night",)
)
EXTENTS = {"spatial": {"bbox": [-180, -90, 180, 90], "crs": CRS84}}


def _parse(
    limits=LIMITS, extents=EXTENTS, style=None, capabilities=CAPABILITIES, accept=None, **params
):
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/collections/roads/map",
        "query_string": urlencode(params).encode(),
        "headers": [] if accept is None else [(b"accept", accept.encode())],
    }
    request = APIRequest(Request(scope), ["en-US"])
    return parse_map_parameters(request, {"extents": extents}, limits, capabilities, style)


def test_a_style_the_provider_does_not_draw_is_not_found():
    with pytest.raises(MapStyleNotFoundError) as error:
        _parse(style="day")

    assert error.value.http_status_code == 404


def test_a_style_the_provider_draws_reaches_it():
    assert _parse(style="night").style == "night"


def test_a_query_parameter_outside_ogc_api_maps_reaches_the_provider():
    parameters = _parse(width=16, height=16, quality="high", **{"x-engine-hint": "fast"})

    assert parameters.vendor_params == {"quality": "high", "x-engine-hint": "fast"}


def test_the_parameters_of_ogc_api_maps_are_not_vendor_parameters():
    standard = {
        "bgcolor": "0xFFFFFF",
        "center": "12.5,41.9",
        "center-crs": CRS84,
        "scale-denominator": "5000",
        "mm-per-pixel": "0.28",
        "orientation": "0",
        "void-color": "0x000000",
        "void-transparent": "true",
        "collections": "roads",
        "subset-crs": CRS84,
        "crs-datum": "WGS84",
        "crs-proj-method": "mercator",
        "crs-proj-params": "1",
        "crs-proj-center": "0,0",
        "lang": "en",
        "f": "png",
    }

    assert _parse(width=16, height=16, **standard).vendor_params == {}


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
        _parse(MapLimits(2048, 2048, 1_000_000), width=1001, height=1000)


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


def test_a_bbox_entirely_outside_the_crs_is_a_map_outside_it():
    outside = _parse(bbox="-1000000,25000000,1000000,30000000", **{"bbox-crs": WEB_MERCATOR})

    assert outside == MapOutsideCrs(bbox=(-1e6, 2.5e7, 1e6, 3e7), crs=WEB_MERCATOR)


def test_a_bbox_above_the_poles_of_web_mercator_is_a_map_outside_it():
    outside = _parse(bbox="10,86,20,89", **{"bbox-crs": CRS84})

    assert isinstance(outside, MapOutsideCrs)
    assert outside.crs == WEB_MERCATOR


def test_a_bbox_in_another_crs_is_not_clipped():
    capabilities = MapCapabilities(
        crs=(WEB_MERCATOR, CRS84), default_crs=CRS84, formats=("png",), styles=()
    )

    parameters = _parse(capabilities=capabilities, bbox="170,-10,-170,10", width=16, height=16)

    assert parameters.bbox == (170.0, -10.0, -170.0, 10.0)


def test_without_crs_the_map_is_drawn_in_the_default_crs():
    capabilities = MapCapabilities(
        crs=(WEB_MERCATOR, CRS84), default_crs=CRS84, formats=("png",), styles=()
    )

    assert _parse(capabilities=capabilities, width=16, height=16).crs == CRS84


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


def test_f_html_is_refused_when_the_provider_draws_no_html():
    with pytest.raises(MapParameterError):
        _parse(f="html")


@pytest.mark.parametrize("accept", ["image/jpeg", "text/html", "image/jpeg, text/html"])
def test_an_accept_without_a_drawn_format_or_a_wildcard_is_not_acceptable(accept):
    with pytest.raises(MapNotAcceptableError) as error:
        _parse(accept=accept, width=16, height=16)

    assert error.value.http_status_code == 406


@pytest.mark.parametrize(
    "accept",
    [
        None,
        "*/*",
        "image/*",
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    ],
)
def test_an_accept_with_a_wildcard_gets_the_first_format(accept):
    assert _parse(accept=accept, width=16, height=16).format_ == "png"


@pytest.mark.parametrize(
    ("accept", "drawn"),
    [
        ("image/jpeg;q=0.5, image/png", "png"),
        ("image/jpeg, image/png;q=0.5", "jpeg"),
        ("image/tiff, image/jpeg;q=0.2", "jpeg"),
    ],
)
def test_the_accepted_format_the_client_prefers_is_drawn(accept, drawn):
    capabilities = MapCapabilities(
        crs=(WEB_MERCATOR,), default_crs=WEB_MERCATOR, formats=("png", "jpeg"), styles=()
    )

    assert _parse(capabilities=capabilities, accept=accept, width=16, height=16).format_ == drawn


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


def test_without_a_bbox_the_map_covers_the_collection_extent():
    rome = {"spatial": {"bbox": [12.4, 41.8, 12.6, 42.0], "crs": CRS84}}
    wide = _parse(width=64, height=64)
    narrow = _parse(extents=rome, width=64, height=64)

    assert narrow.bbox != wide.bbox
    assert narrow.bbox[0] == pytest.approx(1380361.7, abs=1.0)
    assert narrow.bbox[2] == pytest.approx(1402625.6, abs=1.0)


def test_an_extent_without_a_crs_is_read_as_crs84():
    rome = {"spatial": {"bbox": [12.4, 41.8, 12.6, 42.0]}}

    assert _parse(extents=rome, width=64, height=64).bbox[0] == pytest.approx(1380361.7, abs=1.0)


def test_without_datetime_the_map_has_none():
    assert _parse(width=16, height=16).datetime_ is None


@pytest.mark.parametrize(
    "value",
    [
        "yesterday",
        "2020-13-01",
        "2020-01-01/2020-02-01/2020-03-01",
        "2021-01-01/2020-01-01",
        "../..",
    ],
)
def test_a_datetime_that_cannot_be_read_is_refused(value):
    with pytest.raises(MapParameterError):
        _parse(width=16, height=16, datetime=value)


def test_the_route_passes_the_datetime_parsed():
    parameters = _parse(width=16, height=16, datetime="2020-05-01T12:30:00+02:00/..")

    assert parameters.datetime_ == TimeInterval(datetime(2020, 5, 1, 10, 30, tzinfo=UTC), None)
    assert isinstance(parameters.datetime_, TimeInterval)
