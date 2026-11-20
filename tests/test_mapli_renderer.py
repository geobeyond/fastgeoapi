"""The mapli map provider drawing for real, from a local archive and from a bucket."""

import io

import pytest

from tests.mvt_fixtures import land_archive
from tests.pmtiles_fixtures import terrarium_archive

pytestmark = pytest.mark.renderer
mapli = pytest.importorskip("mapli")
Image = pytest.importorskip("PIL.Image")

ROME = [1379000.0, 5140000.0, 1403000.0, 5160000.0]  # EPSG:3857 metres
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
LAND = (247, 205, 206)  # the default style's land fill over white
BUCKET_DATA = "s3://bucket/tiles/land.pmtiles"


def _provider(data, options=None):
    from app.provider.mapli import MapliMapProvider

    return MapliMapProvider(
        {
            "type": "map",
            "name": "app.provider.mapli.MapliMapProvider",
            "data": str(data),
            "storage_crs": WEB_MERCATOR,
            "options": options or {},
        }
    )


async def _map(provider, **kwargs):
    args = {"bbox": list(ROME), "width": 64, "height": 48, "crs": WEB_MERCATOR}
    try:
        return await provider.aquery(**{**args, **kwargs})
    except Exception as error:
        if isinstance(error.__cause__, mapli.GraphicsUnavailableError):
            pytest.skip("no graphics device to draw with")
        raise


def _image(png: bytes):
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _close_to(pixel, colour, tolerance=8) -> bool:
    return all(abs(a - b) <= tolerance for a, b in zip(pixel, colour, strict=False))


@pytest.mark.asyncio
async def test_an_opaque_map_draws_the_land_over_the_background(tmp_path):
    image = _image(
        await _map(_provider(land_archive(tmp_path / "land.pmtiles")), transparent=False)
    )

    assert image.size == (64, 48)
    assert _close_to(image.getpixel((32, 24)), (*LAND, 255))


@pytest.mark.asyncio
async def test_a_transparent_map_lets_the_land_show_through(tmp_path):
    image = _image(await _map(_provider(land_archive(tmp_path / "land.pmtiles")), transparent=True))

    assert 0 < image.getpixel((32, 24))[3] < 255


@pytest.mark.asyncio
async def test_a_bbox_across_the_antimeridian_is_drawn(tmp_path):
    from app.maps.camera import HALF_WORLD

    provider = _provider(land_archive(tmp_path / "land.pmtiles"))
    bbox = [0.9 * HALF_WORLD, -1e6, -0.9 * HALF_WORLD, 1e6]

    image = _image(await _map(provider, bbox=bbox, transparent=False))

    assert _close_to(image.getpixel((32, 24)), (*LAND, 255))


@pytest.mark.asyncio
async def test_a_bbox_is_stretched_over_an_image_of_another_aspect(tmp_path):
    import math

    from app.maps.camera import HALF_WORLD

    # A black square whose south-west corner lies 250 m east and 750 m north of the
    # south-west corner of a 1000 m bbox: a quarter of the way across, three
    # quarters of the way up.
    west = 250 / HALF_WORLD * 180
    south = math.degrees(math.atan(math.sinh(750 / HALF_WORLD * math.pi)))
    square = [[west, south], [1, south], [1, 1], [west, 1], [west, south]]
    corner_style = {
        "version": 8,
        "sources": {
            "square": {
                "type": "geojson",
                "data": {"type": "Polygon", "coordinates": [square]},
            }
        },
        "layers": [
            {"id": "background", "type": "background", "paint": {"background-color": "#ffffff"}},
            {
                "id": "square",
                "type": "fill",
                "source": "square",
                # antialiasing would soften the edges by half a pixel outwards
                "paint": {"fill-color": "#000000", "fill-antialias": False},
            },
        ],
    }
    provider = _provider(
        land_archive(tmp_path / "land.pmtiles"), {"styles": {"corner": corner_style}}
    )

    # The bbox is square, the image twice as wide as it is tall: the corner is at
    # column 32 and row 16. Stretching doubles the width, so the vertical edge
    # blurs over the two columns either side of 32; the horizontal edge stays sharp.
    image = _image(
        await _map(
            provider,
            style="corner",
            bbox=[0.0, 0.0, 1000.0, 1000.0],
            width=128,
            height=64,
            transparent=False,
        )
    )

    black, white = (0, 0, 0, 255), (255, 255, 255, 255)
    assert _close_to(image.getpixel((30, 13)), white)
    assert _close_to(image.getpixel((33, 13)), black)
    assert _close_to(image.getpixel((40, 15)), black)
    assert _close_to(image.getpixel((40, 16)), white)


@pytest.mark.asyncio
async def test_an_elevation_archive_is_shaded(tmp_path):
    provider = _provider(terrarium_archive(tmp_path / "t.pmtiles"), {"dem": "terrarium"})

    image = _image(await _map(provider, bbox=None, width=128, height=128, transparent=False))

    assert len(set(image.getdata())) > 1


@pytest.mark.asyncio
async def test_a_bucket_is_drawn_through_the_scheme_handler(tmp_path):
    from app.provider.storage import CachedRanges
    from tests.loop_guard import loop_guard
    from tests.range_cache_fixtures import CountingStore, memory_store, range_cache

    provider = _provider(BUCKET_DATA)
    origin = CountingStore(memory_store())
    origin.put("land.pmtiles", land_archive(tmp_path / "land.pmtiles").read_bytes())
    provider.cached_ranges = CachedRanges(
        origin, "land.pmtiles", range_cache(memory_store()), source=BUCKET_DATA
    )
    with loop_guard():
        image = _image(await _map(provider, transparent=False))

    assert _close_to(image.getpixel((32, 24)), (*LAND, 255))


@pytest.mark.asyncio
async def test_a_bucket_without_the_range_cache_is_drawn_through_the_scheme_handler(tmp_path):
    from tests.loop_guard import loop_guard
    from tests.range_cache_fixtures import CountingStore, memory_store

    provider = _provider(BUCKET_DATA, {"range_cache": False})
    origin = CountingStore(memory_store())
    origin.put("land.pmtiles", land_archive(tmp_path / "land.pmtiles").read_bytes())
    provider.store = origin
    with loop_guard():
        image = _image(await _map(provider, transparent=False))

    assert provider.cached_ranges is None
    assert origin.range_reads
    assert _close_to(image.getpixel((32, 24)), (*LAND, 255))
