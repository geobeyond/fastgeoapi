"""The server's ceiling on map sizes, the limits of each collection, and where they are published.

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


def test_the_ceiling_defaults_to_2048_and_no_pixel_limit():
    from app.pygeoapi.map_limits import MapCeiling

    assert MapCeiling() == MapCeiling(2048, 2048, None)


def test_the_ceiling_is_published_in_the_info(tmp_path):
    from app.pygeoapi.factory import build_openapi
    from app.pygeoapi.map_limits import MapCeiling

    capped = build_openapi(_roads(tmp_path), map_ceiling=MapCeiling(1500, 1000, 1_000_000))
    default = build_openapi(_roads(tmp_path), map_ceiling=MapCeiling())

    assert capped["info"]["x-OGC-limits"] == {
        "maps": {"maxWidth": 1500, "maxHeight": 1000, "maxPixels": 1_000_000}
    }
    assert default["info"]["x-OGC-limits"] == {"maps": {"maxWidth": 2048, "maxHeight": 2048}}


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


def test_a_collection_above_the_ceiling_is_cut_to_it(tmp_path):
    from app.interfaces.providers import MapLimits
    from app.pygeoapi.factory import build_openapi
    from app.pygeoapi.map_limits import MapCeiling, cut_limits_to_ceiling

    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        document = build_openapi(_roads(tmp_path, max_size=4096))
    finally:
        logger.remove(sink)

    assert _size_schemas(document, MAP)["width"]["maximum"] == 2048
    assert cut_limits_to_ceiling(
        MapLimits(4096, 4096, None, 1, 8, 30.0), MapCeiling()
    ) == MapLimits(2048, 2048, None, 1, 8, 30.0)
    assert any("roads: maps up to 4096x4096 asked, 2048x2048 served" in m for m in messages)


def test_the_smaller_pixel_limit_wins():
    from app.interfaces.providers import MapLimits
    from app.pygeoapi.map_limits import MapCeiling, cut_limits_to_ceiling

    limits = MapLimits(1024, 1024, 500_000, 1, 8, 30.0)

    assert cut_limits_to_ceiling(limits, MapCeiling(2048, 2048, 1_000_000)).max_pixels == 500_000
    assert cut_limits_to_ceiling(limits, MapCeiling(2048, 2048, 100_000)).max_pixels == 100_000
    assert cut_limits_to_ceiling(limits, MapCeiling()).max_pixels == 500_000


def test_the_settings_reach_the_ceiling(monkeypatch):
    from app.config.app import DevConfig
    from app.pygeoapi.map_limits import MapCeiling

    monkeypatch.setenv("DEV_FASTGEOAPI_MAPS_MAX_WIDTH", "1000")
    monkeypatch.setenv("DEV_FASTGEOAPI_MAPS_MAX_PIXELS", "640000")

    assert MapCeiling.from_settings(DevConfig()) == MapCeiling(1000, 2048, 640_000)


@pytest.mark.parametrize("setting", ["FASTGEOAPI_MAPS_MAX_WIDTH", "FASTGEOAPI_MAPS_MAX_HEIGHT"])
def test_the_sides_default_to_2048_in_the_settings(monkeypatch, setting):
    from app.config.app import DevConfig

    monkeypatch.delenv(f"DEV_{setting}", raising=False)

    assert getattr(DevConfig(), setting) == 2048
