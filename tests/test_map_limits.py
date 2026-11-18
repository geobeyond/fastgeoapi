"""The server's limits on map sizes, the limits of each collection, and where they are published.

``app.*`` is imported inside the tests, nowhere else.
"""

import pytest
from loguru import logger

from tests.maps_fixtures import map_provider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config

MAP = "/collections/roads/map"
STYLED = "/collections/roads/styles/{styleId}/map"


def _archive(folder):
    return write_archive(folder / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})


def _roads(folder, **options) -> dict:
    style = folder / "night.json"
    style.write_text('{"version": 8, "sources": {}, "layers": []}')
    definition = map_provider(_archive(folder), styles={"night": str(style)}, **options)
    return _config({"roads": _collection("Roads", [definition])})


def _size_schemas(document: dict, path: str) -> dict[str, dict]:
    parameters = document["paths"][path]["get"]["parameters"]
    return {p["name"]: p["schema"] for p in parameters if p.get("name") in ("width", "height")}


def test_the_server_limits_default_to_2048_and_no_pixel_limit(tmp_path):
    from app.config.app import ProdConfig
    from app.pygeoapi.factory import build_openapi

    document = build_openapi(_roads(tmp_path), settings=ProdConfig.model_construct())

    assert document["info"]["x-OGC-limits"] == {"maps": {"maxWidth": 2048, "maxHeight": 2048}}


def test_the_server_limits_are_published_in_the_info(tmp_path):
    from app.config.app import ProdConfig
    from app.pygeoapi.factory import build_openapi

    settings = ProdConfig.model_construct(
        FASTGEOAPI_MAPS_MAX_WIDTH=1500,
        FASTGEOAPI_MAPS_MAX_HEIGHT=1000,
        FASTGEOAPI_MAPS_MAX_PIXELS=1_000_000,
    )

    document = build_openapi(_roads(tmp_path), settings=settings)

    assert document["info"]["x-OGC-limits"] == {
        "maps": {"maxWidth": 1500, "maxHeight": 1000, "maxPixels": 1_000_000}
    }


def test_a_document_without_maps_publishes_no_map_limits():
    from app.pygeoapi.factory import build_openapi

    document = build_openapi(_config({}))

    assert "x-OGC-limits" not in document["info"]


def test_each_map_operation_publishes_the_limits_of_its_collection(tmp_path):
    from app.pygeoapi.factory import build_openapi

    document = build_openapi(_roads(tmp_path, max_size=1024))

    for path in (MAP, STYLED):
        assert _size_schemas(document, path) == {
            "width": {"type": "integer", "minimum": 1, "maximum": 1024},
            "height": {"type": "integer", "minimum": 1, "maximum": 1024},
        }


def test_a_collection_above_the_server_limits_is_clamped_to_them(tmp_path):
    from app.config.app import ProdConfig
    from app.interfaces.providers import MapLimits
    from app.pygeoapi.factory import build_openapi
    from app.pygeoapi.map_limits import clamp_provider_map_limits

    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        document = build_openapi(
            _roads(tmp_path, max_size=4096), settings=ProdConfig.model_construct()
        )
    finally:
        logger.remove(sink)

    assert _size_schemas(document, MAP)["width"]["maximum"] == 2048
    assert clamp_provider_map_limits(MapLimits(4096, 4096, None), 2048, 2048, None) == MapLimits(
        2048, 2048, None
    )
    assert any("roads: maps up to 4096x4096 asked, 2048x2048 served" in m for m in messages)


def test_the_smaller_pixel_limit_wins():
    from app.interfaces.providers import MapLimits
    from app.pygeoapi.map_limits import clamp_provider_map_limits

    limits = MapLimits(1024, 1024, 500_000)

    assert clamp_provider_map_limits(limits, 2048, 2048, 1_000_000).max_pixels == 500_000
    assert clamp_provider_map_limits(limits, 2048, 2048, 100_000).max_pixels == 100_000
    assert clamp_provider_map_limits(limits, 2048, 2048, None).max_pixels == 500_000


def test_the_settings_reach_the_published_limits(monkeypatch, tmp_path):
    from app.config.app import DevConfig
    from app.pygeoapi.factory import build_openapi

    monkeypatch.setenv("DEV_FASTGEOAPI_MAPS_MAX_WIDTH", "1000")
    monkeypatch.setenv("DEV_FASTGEOAPI_MAPS_MAX_PIXELS", "640000")

    document = build_openapi(_roads(tmp_path), settings=DevConfig())

    assert document["info"]["x-OGC-limits"] == {
        "maps": {"maxWidth": 1000, "maxHeight": 2048, "maxPixels": 640_000}
    }


def test_without_settings_the_document_takes_those_of_the_running_server(tmp_path):
    from app.config.app import configuration
    from app.pygeoapi.factory import build_openapi

    document = build_openapi(_roads(tmp_path))

    assert document["info"]["x-OGC-limits"]["maps"]["maxWidth"] == (
        configuration.FASTGEOAPI_MAPS_MAX_WIDTH
    )


@pytest.mark.parametrize("unavailable", ["unimportable", "no environment"])
def test_without_a_configured_server_the_default_limits_apply(monkeypatch, unavailable):
    import sys

    from app.pygeoapi.map_limits import get_server_map_limits

    if unavailable == "unimportable":
        monkeypatch.setitem(sys.modules, "app.config.app", None)
    else:
        import app.config.app

        monkeypatch.setattr(app.config.app, "configuration", None)

    assert get_server_map_limits(None) == (2048, 2048, None)


def test_the_settings_passed_give_the_server_limits():
    from app.config.app import ProdConfig
    from app.pygeoapi.map_limits import get_server_map_limits

    settings = ProdConfig.model_construct(
        FASTGEOAPI_MAPS_MAX_WIDTH=1500, FASTGEOAPI_MAPS_MAX_PIXELS=1_000_000
    )

    assert get_server_map_limits(settings) == (1500, 2048, 1_000_000)
