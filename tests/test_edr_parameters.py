"""The EDR query parameters the route checks and normalises before any provider sees them.

``app.*`` is imported at the top of this module, nowhere else.
"""

import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import pytest
from pygeoapi.api import APIRequest
from shapely.geometry import MultiPoint, Point, Polygon
from starlette.requests import Request

from app.interfaces.providers import (
    AreaQuery,
    EdrCapabilities,
    EdrFormat,
    EdrParameter,
    PositionQuery,
)
from app.provider.edr import (
    EdrNotAcceptableError,
    EdrParameterError,
    EdrQueryNotOfferedError,
)
from app.pygeoapi.api_async.edr_parameters import (
    EdrOutsideExtent,
    describe_edr_query,
    parse_edr_query,
)
from app.schemas.temporal import TimeInterval

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
CAPABILITIES = EdrCapabilities(
    query_types=("position", "area"),
    crs=(CRS84,),
    default_crs=CRS84,
    formats=(EdrFormat.COVERAGEJSON,),
    parameters=(
        EdrParameter("t2m", "Temperature", "K"),
        EdrParameter("precip", "Precipitation", "mm"),
    ),
)
EXTENTS = {
    "spatial": {"bbox": [[-10, 30, 30, 60]], "crs": CRS84},
    "temporal": {
        "begin": datetime(2020, 1, 1, tzinfo=UTC),
        "end": datetime(2020, 12, 31, tzinfo=UTC),
    },
}
POINT = "POINT(10 40)"
POLYGON = "POLYGON((0 40, 10 40, 10 50, 0 50, 0 40))"


def _parse(
    query_type="position", extents=EXTENTS, accept=None, capabilities=CAPABILITIES, **params
):
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/collections/era5/{query_type}",
        "query_string": urlencode(params).encode(),
        "headers": [] if accept is None else [(b"accept", accept.encode())],
    }
    request = APIRequest(Request(scope), ["en-US"])
    return parse_edr_query(request, {"extents": extents}, query_type, capabilities, 1000)


@pytest.mark.parametrize("query_type", ["cube", "radius", "instances", "trajectory", "locations"])
def test_a_query_type_not_offered_is_not_found(query_type):
    with pytest.raises(EdrQueryNotOfferedError) as error:
        _parse(query_type, coords=POINT)

    assert error.value.http_status_code == 404
    assert error.value.ogc_exception_code == "NotFound"


def test_coords_is_required():
    with pytest.raises(EdrParameterError) as error:
        _parse()

    assert error.value.http_status_code == 400
    assert error.value.ogc_exception_code == "InvalidParameterValue"


@pytest.mark.parametrize("coords", ["10,40", "POINT(", "POINT EMPTY", ""])
def test_coords_must_be_wkt(coords):
    with pytest.raises(EdrParameterError):
        _parse(coords=coords)


def test_position_takes_a_point_or_a_multipoint():
    assert isinstance(_parse(coords=POINT).coords, Point)
    assert isinstance(_parse(coords="MULTIPOINT((10 40),(11 41))").coords, MultiPoint)
    with pytest.raises(EdrParameterError):
        _parse(coords=POLYGON)


def test_area_takes_a_polygon_or_a_multipolygon():
    query = _parse("area", coords=POLYGON)
    assert isinstance(query, AreaQuery)
    assert isinstance(query.coords, Polygon)
    multi = "MULTIPOLYGON(((0 40, 1 40, 1 41, 0 40)),((5 40, 6 40, 6 41, 5 40)))"
    assert _parse("area", coords=multi).coords.geom_type == "MultiPolygon"
    with pytest.raises(EdrParameterError):
        _parse("area", coords=POINT)


def test_a_position_query_is_a_position_query():
    query = _parse(coords=POINT)

    assert isinstance(query, PositionQuery)
    assert query.max_values == 1000


def test_a_point_outside_the_extent_is_answered_204():
    assert isinstance(_parse(coords="POINT(100 40)"), EdrOutsideExtent)
    assert isinstance(_parse(coords="MULTIPOINT((100 40),(101 41))"), EdrOutsideExtent)
    assert isinstance(_parse(coords="MULTIPOINT((100 40),(10 40))"), PositionQuery)
    assert isinstance(
        _parse("area", coords="POLYGON((50 40, 60 40, 60 50, 50 40))"), EdrOutsideExtent
    )
    assert isinstance(_parse("area", coords=POLYGON), AreaQuery)


def test_any_box_of_the_extent_counts():
    extents = {"spatial": {"bbox": [[-10, 30, 30, 60], [100, 0, 110, 10]]}}

    assert isinstance(_parse(extents=extents, coords="POINT(105 5)"), PositionQuery)


def test_without_a_spatial_extent_nothing_is_outside():
    assert isinstance(_parse(extents={}, coords="POINT(100 40)"), PositionQuery)


def test_parameter_names_are_split_on_commas_and_trimmed():
    query = _parse(coords=POINT, **{"parameter-name": "t2m, precip"})

    assert query.parameter_names == ("t2m", "precip")


def test_an_unknown_parameter_name_is_rejected():
    with pytest.raises(EdrParameterError):
        _parse(coords=POINT, **{"parameter-name": "T2M"})


def test_no_parameter_name_means_every_parameter():
    assert _parse(coords=POINT).parameter_names == ("t2m", "precip")
    assert _parse(coords=POINT, **{"parameter-name": ""}).parameter_names == ("t2m", "precip")


def test_datetime_is_checked_against_the_temporal_extent():
    with pytest.raises(EdrParameterError):
        _parse(coords=POINT, datetime="2021-06-01T00:00:00Z")
    query = _parse(coords=POINT, datetime="2020-02-01/2020-03-01")
    assert isinstance(query.datetime_, TimeInterval)
    assert _parse(coords=POINT).datetime_ is None


def test_a_malformed_datetime_is_rejected():
    with pytest.raises(EdrParameterError):
        _parse(coords=POINT, datetime="yesterday")


def test_z_is_rejected_without_a_vertical_axis():
    with pytest.raises(EdrParameterError) as error:
        _parse(coords=POINT, z="10")

    assert "no vertical axis" in str(error.value.user_msg)


def test_resolution_must_be_a_positive_integer():
    for value in ("0", "-1", "a"):
        with pytest.raises(EdrParameterError):
            _parse("area", coords=POLYGON, **{"resolution-x": value})
        with pytest.raises(EdrParameterError):
            _parse("area", coords=POLYGON, **{"resolution-y": value})
    query = _parse("area", coords=POLYGON, **{"resolution-x": "5", "resolution-y": "7"})
    assert (query.resolution_x, query.resolution_y) == (5, 7)
    assert _parse("area", coords=POLYGON).resolution_x is None


def test_crs_must_be_declared():
    with pytest.raises(EdrParameterError):
        _parse(coords=POINT, crs="http://www.opengis.net/def/crs/EPSG/0/3857")


def test_crs_defaults_to_default_crs():
    assert _parse(coords=POINT).crs == CRS84
    assert _parse(coords=POINT, crs=CRS84.lower()).crs == CRS84


def test_f_outside_the_formats_is_400():
    with pytest.raises(EdrParameterError) as error:
        _parse(coords=POINT, f="GeoJSON")

    assert error.value.http_status_code == 400


def test_accept_without_a_format_is_406():
    with pytest.raises(EdrNotAcceptableError) as error:
        _parse(coords=POINT, accept="text/html")

    assert error.value.http_status_code == 406


def test_f_coveragejson_is_chosen():
    assert _parse(coords=POINT, f="CoverageJSON").format_ == "CoverageJSON"
    assert _parse(coords=POINT, accept="application/prs.coverage+json").format_ == "CoverageJSON"
    assert _parse(coords=POINT, accept="*/*").format_ == "CoverageJSON"
    assert _parse(coords=POINT).format_ == "CoverageJSON"


def test_vendor_params_are_kept():
    query = _parse(coords=POINT, f="CoverageJSON", engine="fast")

    assert query.vendor_params == {"engine": "fast"}


def test_describe_edr_query_is_json_ready():
    query = _parse(coords=POINT, datetime="2020-02-01/..", **{"parameter-name": "t2m"})

    description = describe_edr_query(query)

    assert description["coords"] == "POINT (10 40)"
    assert description["parameter_names"] == ["t2m"]
    assert description["datetime"] == "2020-02-01T00:00:00+00:00/.."
    json.dumps(description)


def test_an_application_wildcard_chooses_coveragejson():
    assert _parse(coords=POINT, accept="application/*").format_ == "CoverageJSON"


def test_a_wildcard_of_another_type_is_406():
    with pytest.raises(EdrNotAcceptableError):
        _parse(coords=POINT, accept="text/*")


def test_a_query_type_the_parser_does_not_read_is_not_found():
    capabilities = EdrCapabilities(
        query_types=("position", "cube"),
        crs=CAPABILITIES.crs,
        default_crs=CRS84,
        formats=CAPABILITIES.formats,
        parameters=CAPABILITIES.parameters,
    )

    with pytest.raises(EdrQueryNotOfferedError):
        _parse("cube", capabilities=capabilities, coords=POINT)
