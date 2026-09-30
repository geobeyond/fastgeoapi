"""The PMTiles provider on raster archives: what it refuses, what it serves, how it describes it.

Imports stay at module level, like the other PMTiles test modules.
"""

import pytest
from pmtiles.tile import TileType
from pygeoapi.provider.base import ProviderGenericError
from starlette.testclient import TestClient

from app.provider.pmtiles import PMTilesProvider
from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
from tests.pmtiles_fixtures import TILE_BYTES, raster_archive, write_archive
from tests.test_tiles_async_route import _collection, _config

SERVER = "http://localhost:5000/geoapi"
PNG = {"name": "png", "mimetype": "image/png"}
WEBP = {"name": "webp", "mimetype": "image/webp"}
MVT = {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"}


def _definition(path, format_=PNG, **options) -> dict:
    return {
        "type": "tile",
        "name": "app.provider.pmtiles.PMTilesProvider",
        "data": str(path),
        "options": {"zoom": {"min": 0, "max": 8}, "schemes": ["WebMercatorQuad"], **options},
        "format": format_,
    }


def _client(definition) -> TestClient:
    config = _config({"hills": _collection("Hills", [definition])})
    return TestClient(
        build_pygeoapi_subapp(config, build_openapi(config)), raise_server_exceptions=False
    )


def test_a_raster_archive_configured_as_vector_names_the_format_to_write(tmp_path):
    archive = raster_archive(tmp_path / "flowers.pmtiles", kind="WEBP")

    with pytest.raises(ProviderGenericError) as error:
        PMTilesProvider(_definition(archive, MVT)).get_tiles(z=0, x=0, y=0)
    assert error.value.message == (
        "the archive holds WEBP tiles: set format to {name: webp, mimetype: image/webp}"
    )


@pytest.mark.asyncio
async def test_the_async_face_refuses_it_too(tmp_path):
    archive = raster_archive(tmp_path / "flowers.pmtiles", kind="WEBP")

    with pytest.raises(ProviderGenericError):
        await PMTilesProvider(_definition(archive, MVT)).aget_tiles(z=0, x=0, y=0)


@pytest.mark.parametrize("tile_type", [TileType.UNKNOWN, TileType.MLT])
def test_an_archive_of_unknown_or_mlt_tiles_is_refused(tmp_path, tile_type):
    archive = write_archive(
        tmp_path / "odd.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)}, tile_type=tile_type
    )

    with pytest.raises(ProviderGenericError) as error:
        PMTilesProvider(_definition(archive, MVT)).get_tiles(z=0, x=0, y=0)
    assert error.value.message == f"PMTiles tiles of type {tile_type.name} are not supported"


def test_an_elevation_archive_of_jpeg_tiles_is_refused(tmp_path):
    archive = raster_archive(tmp_path / "terrain.pmtiles", kind="JPEG")
    jpeg = {"name": "jpg", "mimetype": "image/jpeg"}

    with pytest.raises(ProviderGenericError) as error:
        PMTilesProvider(_definition(archive, jpeg, dem="terrarium")).get_tiles(z=0, x=0, y=0)
    assert error.value.message == "an elevation archive needs PNG or WebP tiles, not JPEG"


def test_the_tilejson_of_a_mismatched_archive_is_refused_too(tmp_path):
    archive = raster_archive(tmp_path / "flowers.pmtiles", kind="WEBP")

    with pytest.raises(ProviderGenericError):
        PMTilesProvider(_definition(archive, MVT)).get_vendor_metadata(
            "hills", SERVER, "hills", "WebMercatorQuad", "Hills", "Hills", []
        )


def test_through_the_route_the_refusal_is_a_500_with_the_format_to_write(tmp_path):
    archive = raster_archive(tmp_path / "flowers.pmtiles", kind="WEBP")

    r = _client(_definition(archive, MVT)).get(
        "/collections/hills/tiles/WebMercatorQuad/0/0/0", params={"f": "mvt"}
    )
    assert r.status_code == 500
    assert "set format to {name: webp, mimetype: image/webp}" in r.text
