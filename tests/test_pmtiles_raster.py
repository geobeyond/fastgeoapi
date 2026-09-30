"""The PMTiles provider on raster archives: what it refuses, what it serves, how it describes it.

Imports stay at module level, like the other PMTiles test modules.
"""

import pytest
from pmtiles.tile import Compression, TileType, deserialize_directory, deserialize_header
from pygeoapi.provider.base import ProviderGenericError
from starlette.testclient import TestClient

from app.provider.pmtiles import PMTilesProvider
from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp
from tests.pmtiles_fixtures import TILE_BYTES, raster_archive, raster_tile, write_archive
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


def _metadata(provider, name="hills"):
    return provider.get_default_metadata(
        name, SERVER, name, "WebMercatorQuad", name.title(), name.title(), [name]
    )


def _tilejson(provider, name="hills"):
    return provider.get_vendor_metadata(
        name, SERVER, name, "WebMercatorQuad", name.title(), name.title(), [name]
    )


def test_a_raster_tileset_is_a_map_with_image_links(tmp_path):
    metadata = _metadata(PMTilesProvider(_definition(raster_archive(tmp_path / "hills.pmtiles"))))

    item = next(link for link in metadata["links"] if link["rel"] == "item")
    assert metadata["dataType"] == "map"
    assert item["type"] == "image/png"
    assert item["href"].endswith("?f=png")
    assert item["title"] == "WebMercatorQuad map tiles for hills"


def test_an_elevation_tileset_is_a_coverage(tmp_path):
    provider = PMTilesProvider(
        _definition(raster_archive(tmp_path / "terrain.pmtiles"), dem="terrarium")
    )

    metadata = _metadata(provider, "terrain")
    item = next(link for link in metadata["links"] if link["rel"] == "item")
    assert metadata["dataType"] == "coverage"
    assert item["title"] == "WebMercatorQuad elevation tiles for terrain"


def test_the_tilejson_of_a_raster_archive_is_what_maplibre_reads(tmp_path):
    archive = raster_archive(tmp_path / "hills.pmtiles", size=512)

    assert _tilejson(PMTilesProvider(_definition(archive))) == {
        "tilejson": "3.0.0",
        "name": "hills",
        "tiles": [f"{SERVER}/collections/hills/tiles/WebMercatorQuad/{{z}}/{{y}}/{{x}}?f=png"],
        "minzoom": 0,
        "maxzoom": 0,
        "bounds": [-180.0, -85.0511287, 180.0, 85.0511287],
        "center": [0.0, 0.0, 0],
        "tileSize": 512,
    }


def test_the_tilejson_of_an_elevation_archive_names_its_encoding(tmp_path):
    provider = PMTilesProvider(
        _definition(raster_archive(tmp_path / "terrain.pmtiles"), dem="mapbox")
    )

    tilejson = _tilejson(provider, "terrain")
    assert (tilejson["encoding"], tilejson["tileSize"]) == ("mapbox", 256)


def test_the_tile_size_option_wins_over_the_tiles(tmp_path):
    archive = raster_archive(tmp_path / "hills.pmtiles", size=512)

    assert _tilejson(PMTilesProvider(_definition(archive, tile_size=256)))["tileSize"] == 256


def test_the_tile_size_is_read_through_a_leaf_directory(tmp_path):
    tile = raster_tile(256)
    # Distinct bytes per tile, so the writer keeps one entry each and spills into leaves.
    tiles = {(8, i % 256, (i // 256) % 256): tile + i.to_bytes(4, "big") for i in range(20_000)}
    archive = write_archive(
        tmp_path / "big.pmtiles",
        tiles,
        metadata={"name": "big"},
        tile_compression=Compression.NONE,
        tile_type=TileType.PNG,
    )
    data = archive.read_bytes()
    header = deserialize_header(data[:127])
    start = header["root_offset"]
    root = deserialize_directory(data[start : start + header["root_length"]])
    assert root[0].run_length == 0  # the first root entry points to a leaf

    assert _tilejson(PMTilesProvider(_definition(archive)), "big")["tileSize"] == 256


def test_a_gzipped_raster_tile_goes_out_as_the_image(tmp_path):
    """Guard: a gzip-compressed raster tile goes out inflated, as the image itself."""
    archive = raster_archive(tmp_path / "hills.pmtiles", gzipped=True)

    assert PMTilesProvider(_definition(archive)).get_tiles(z=0, x=0, y=0) == raster_tile(256)


def test_through_the_route_a_raster_tile_goes_out_as_stored(tmp_path):
    """Guard: the tile goes out byte for byte as stored, under the configured media type."""
    client = _client(_definition(raster_archive(tmp_path / "hills.pmtiles", kind="WEBP"), WEBP))

    r = client.get("/collections/hills/tiles/WebMercatorQuad/0/0/0", params={"f": "webp"})
    assert (r.status_code, r.headers["content-type"], r.content) == (
        200,
        "image/webp",
        raster_tile(kind="WEBP"),
    )


def test_through_the_route_the_tilejson_template_reaches_the_tile(tmp_path):
    client = _client(_definition(raster_archive(tmp_path / "hills.pmtiles", kind="WEBP"), WEBP))

    tilejson = client.get(
        "/collections/hills/tiles/WebMercatorQuad/metadata", params={"f": "tilejson"}
    ).json()
    url = tilejson["tiles"][0].format(z=0, x=0, y=0).removeprefix("http://localhost:5000")
    r = client.get(url)
    assert (r.status_code, r.headers["content-type"]) == (200, "image/webp")


def test_through_the_route_the_tileset_says_map(tmp_path):
    client = _client(_definition(raster_archive(tmp_path / "hills.pmtiles")))

    metadata = client.get("/collections/hills/tiles/WebMercatorQuad", params={"f": "json"}).json()
    assert metadata["dataType"] == "map"


def test_through_the_route_the_tilejson_of_a_mismatched_archive_names_the_format_to_write(
    tmp_path,
):
    archive = raster_archive(tmp_path / "flowers.pmtiles", kind="WEBP")

    r = _client(_definition(archive, MVT)).get(
        "/collections/hills/tiles/WebMercatorQuad/metadata", params={"f": "tilejson"}
    )
    assert r.status_code == 500
    assert "set format to {name: webp, mimetype: image/webp}" in r.text


def test_through_the_route_the_tilesets_page_draws_raster_tiles(tmp_path):
    client = _client(_definition(raster_archive(tmp_path / "hills.pmtiles")))

    r = client.get("/collections/hills/tiles", params={"f": "html"})
    assert r.status_code == 200
    # The raster branch of pygeoapi's template, the only one with this option:
    # it is rendered for tile_type "raster" alone.
    assert "crs: 'EPSG:3857'" in r.text
