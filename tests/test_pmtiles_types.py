"""What a PMTiles tile type allows: media types, elevation encodings, tile widths."""

import io

import pytest
from PIL import Image
from pmtiles.tile import TileType

from app.provider.dem import check_dem
from app.provider.pmtiles_types import tile_width, tiles_problem
from tests.pmtiles_fixtures import raster_tile


@pytest.mark.parametrize("tile_type", [TileType.UNKNOWN, TileType.MLT])
def test_unknown_and_mlt_tiles_are_refused(tile_type):
    assert tiles_problem(tile_type, media_type=None, dem=None) == (
        f"PMTiles tiles of type {tile_type.name} are not supported"
    )


def test_a_media_type_that_does_not_match_the_archive_names_the_format_to_write():
    problem = tiles_problem(
        TileType.WEBP, media_type="application/vnd.mapbox-vector-tile", dem=None
    )
    assert problem == (
        "the archive holds WEBP tiles: set format to {name: webp, mimetype: image/webp}"
    )


def test_a_matching_media_type_or_none_at_all_is_fine():
    assert tiles_problem(TileType.PNG, media_type="image/png", dem=None) is None
    assert tiles_problem(TileType.MVT, media_type="application/x-protobuf", dem=None) is None
    assert tiles_problem(TileType.MVT, media_type=None, dem=None) is None


@pytest.mark.parametrize("tile_type", [TileType.JPEG, TileType.AVIF, TileType.MVT])
def test_an_elevation_archive_needs_lossless_raster_tiles(tile_type):
    assert tiles_problem(tile_type, media_type=None, dem="terrarium") == (
        f"an elevation archive needs PNG or WebP tiles, not {tile_type.name}"
    )


def test_the_dem_option_takes_the_encodings_maplibre_reads():
    assert check_dem(None) is None
    assert check_dem("mapbox") == "mapbox"
    with pytest.raises(ValueError, match="terrarium, mapbox, not srtm"):
        check_dem("srtm")


@pytest.mark.parametrize("size", [256, 512])
@pytest.mark.parametrize(
    ("kind", "tile_type"),
    [("PNG", TileType.PNG), ("JPEG", TileType.JPEG), ("WEBP", TileType.WEBP)],
)
def test_the_width_of_a_tile_is_read_from_its_bytes(size, kind, tile_type):
    assert tile_width(raster_tile(size, kind=kind), tile_type) == size


def test_the_width_of_a_lossless_webp_tile_is_read_too():
    buffer = io.BytesIO()
    Image.new("RGB", (512, 512), (1, 2, 3)).save(buffer, format="WEBP", lossless=True)
    assert tile_width(buffer.getvalue(), TileType.WEBP) == 512


def test_a_tile_whose_width_cannot_be_read_has_none():
    assert tile_width(b"not an image", TileType.PNG) is None
    assert tile_width(b"\x00\x00\x00\x1cftypavif", TileType.AVIF) is None
