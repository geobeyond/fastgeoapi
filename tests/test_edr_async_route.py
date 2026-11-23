"""The EDR route: a native provider is awaited, the others keep pygeoapi's threadpool."""

import logging

import pytest
from starlette.testclient import TestClient

from app.config.app import ProdConfig
from app.pygeoapi.api_async.caching import HttpCache
from app.pygeoapi.edr_limits import clamp_edr_limit
from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
from tests.edr_fixtures import CRS84, FakeEdrProvider, edr_provider
from tests.test_tiles_async_route import _collection, _config

POINT = "POINT(10 40)"
POLYGON = "POLYGON((0 40, 10 40, 10 50, 0 50, 0 40))"
MEDIA_TYPE = "application/prs.coverage+json"


def _open(definition: dict, settings=None, *, cached: bool = False) -> TestClient:
    config = _config({"era5": _collection("ERA5", [definition])})
    app = build_pygeoapi_subapp(
        config,
        build_openapi(config, settings=settings),
        http_cache=HttpCache(max_age=300, protected=False, code="edr") if cached else None,
        settings=settings,
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client():
    FakeEdrProvider.queries.clear()
    with _open(edr_provider()) as opened:
        yield opened


def test_a_native_position_answers_coveragejson(client):
    response = client.get("/collections/era5/position", params={"coords": POINT})

    assert response.status_code == 200
    assert response.headers["content-type"] == MEDIA_TYPE
    assert response.headers["content-crs"] == CRS84
    assert response.json()["type"] == "Coverage"


def test_a_native_area_answers_coveragejson(client):
    response = client.get("/collections/era5/area", params={"coords": POLYGON})

    assert response.status_code == 200
    assert response.headers["content-type"] == MEDIA_TYPE


def test_a_collection_without_a_native_provider_keeps_pygeoapi():
    definition = {**edr_provider(), "name": "tests.edr_fixtures.ThreadedEdrProvider"}
    FakeEdrProvider.queries.clear()
    with _open(definition) as opened:
        response = opened.get("/collections/era5/position", params={"coords": POINT})

    assert FakeEdrProvider.queries == []
    assert response.status_code == 200
    assert response.headers["content-type"] != MEDIA_TYPE
    assert response.json()["served"] == "pygeoapi"


@pytest.mark.parametrize(
    "path",
    ["cube", "radius", "instances", "trajectory", "corridor", "locations", "instances/a/position"],
)
def test_a_query_type_not_offered_is_404(client, path):
    response = client.get(f"/collections/era5/{path}", params={"coords": POINT})

    assert response.status_code == 404


def test_a_parameter_error_is_400_without_a_traceback(client, caplog):
    with caplog.at_level(logging.DEBUG):
        response = client.get("/collections/era5/position", params={"coords": "nonsense"})

    assert response.status_code == 400
    assert not [record for record in caplog.records if record.exc_info]


def test_outside_the_extent_is_204():
    config = _config({"era5": _collection("ERA5", [edr_provider()])})
    config["resources"]["era5"]["extents"]["spatial"]["bbox"] = [-10, 30, 30, 60]
    FakeEdrProvider.queries.clear()
    app = build_pygeoapi_subapp(config, build_openapi(config))
    with TestClient(app, raise_server_exceptions=False) as opened:
        response = opened.get("/collections/era5/position", params={"coords": "POINT(100 -40)"})

    assert response.status_code == 204
    assert response.content == b""
    assert FakeEdrProvider.queries == []


def test_no_data_found_is_204():
    with _open(edr_provider(fail="no_data")) as opened:
        response = opened.get("/collections/era5/position", params={"coords": POINT})

    assert response.status_code == 204
    assert response.content == b""


def test_data_too_large_is_413_and_names_the_limit():
    with _open(edr_provider(max_values=1)) as opened:
        response = opened.get(
            "/collections/era5/position", params={"coords": "MULTIPOINT((1 1), (2 2), (3 3))"}
        )

    assert response.status_code == 413
    message = response.text
    assert "3" in message
    assert "limit" in message
    assert "1" in message


def test_the_server_cap_lowers_the_provider_limit():
    settings = ProdConfig.model_construct(FASTGEOAPI_EDR_MAX_VALUES=10)
    FakeEdrProvider.queries.clear()
    with _open(edr_provider(max_values=100), settings) as opened:
        points = ", ".join(f"({n} 40)" for n in range(11))
        response = opened.get(
            "/collections/era5/position", params={"coords": f"MULTIPOINT({points})"}
        )

    assert response.status_code == 413
    assert FakeEdrProvider.queries[-1].max_values == 10


def test_clamp_edr_limit_takes_the_smaller():
    from app.interfaces.providers import EdrLimits

    assert clamp_edr_limit(EdrLimits(max_values=None), 10) == 10
    assert clamp_edr_limit(EdrLimits(max_values=100), 10) == 10
    assert clamp_edr_limit(EdrLimits(max_values=5), 10) == 5


@pytest.mark.parametrize(
    ("options", "status", "retry_after"),
    [
        ({"fail": "busy", "retry_after": 5}, 503, "5"),
        ({"fail": "timeout"}, 504, None),
    ],
)
def test_not_retrieved_data_keeps_its_status_and_retry_after(options, status, retry_after):
    with _open(edr_provider(**options)) as opened:
        response = opened.get("/collections/era5/position", params={"coords": POINT})

    assert response.status_code == status
    assert response.headers.get("retry-after") == retry_after


def test_an_etag_answers_304():
    FakeEdrProvider.queries.clear()
    with _open(edr_provider(), cached=True) as opened:
        first = opened.get("/collections/era5/position", params={"coords": POINT})
        etag = first.headers["etag"]
        before = len(FakeEdrProvider.queries)
        second = opened.get(
            "/collections/era5/position",
            params={"coords": POINT},
            headers={"If-None-Match": etag},
        )

    assert first.status_code == 200
    assert "cache-control" in first.headers
    assert second.status_code == 304
    assert len(FakeEdrProvider.queries) == before


def test_a_changed_version_drops_the_cache_headers():
    with _open(edr_provider(version=None), cached=True) as opened:
        response = opened.get("/collections/era5/position", params={"coords": POINT})

    assert response.status_code == 200
    assert "etag" not in response.headers
    assert "cache-control" not in response.headers


def test_extra_headers_cannot_override_reserved_ones():
    extra = {"Content-Type": "text/plain", "ETag": "forged", "X-Source": "grid"}
    with _open(edr_provider(extra_headers=extra), cached=True) as opened:
        response = opened.get("/collections/era5/position", params={"coords": POINT})

    assert response.headers["content-type"] == MEDIA_TYPE
    assert response.headers["etag"] != "forged"
    assert response.headers["x-source"] == "grid"
