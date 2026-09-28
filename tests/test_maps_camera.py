"""Where a MapLibre camera points so that an EPSG:3857 bbox fills the image."""

import pytest
from pyproj import Transformer

from app.maps.camera import HALF_WORLD, TILE_SIZE, camera_for_bbox
from app.maps.contract import MapRequest

_TO_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def _bbox_3857(lon0, lat0, lon1, lat1):
    x0, y0 = _TO_3857.transform(lon0, lat0)
    x1, y1 = _TO_3857.transform(lon1, lat1)
    return (x0, y0, x1, y1)


def _bbox_from_camera(camera):
    """The EPSG:3857 extent a camera shows at its render size."""
    world = 2 * HALF_WORLD
    n = TILE_SIZE * 2**camera.zoom
    lon, lat = camera.center
    x, y = _TO_3857.transform(lon, lat)
    cx = (x + HALF_WORLD) / world * n
    cy = (HALF_WORLD - y) / world * n
    width, height = camera.size

    def to_x(px):
        return px / n * world - HALF_WORLD

    def to_y(py):
        return HALF_WORLD - py / n * world

    return (
        to_x(cx - width / 2),
        to_y(cy + height / 2),
        to_x(cx + width / 2),
        to_y(cy - height / 2),
    )


@pytest.mark.parametrize(
    ("lonlat", "width", "height"),
    [
        ((11.22, 43.75, 11.29, 43.79), 1024, 768),
        ((12.3, 41.8, 12.6, 42.0), 800, 800),
        ((-10, 35, 30, 60), 512, 400),
    ],
)
def test_the_camera_shows_exactly_the_bbox(lonlat, width, height):
    bbox = _bbox_3857(*lonlat)
    camera = camera_for_bbox(bbox, width, height)
    got = _bbox_from_camera(camera)
    pixel = (bbox[2] - bbox[0]) / camera.size[0]

    for side in range(4):
        assert got[side] == pytest.approx(bbox[side], abs=pixel)


def test_the_center_is_the_mercator_midpoint():
    camera = camera_for_bbox(_bbox_3857(0, 0, 10, 60), 512, 512)

    assert camera.center[1] > 30.5  # the mean of the latitudes would be 30


def test_the_whole_world_at_512_pixels_is_zoom_zero():
    camera = camera_for_bbox((-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD), 512, 512)

    assert camera.zoom == pytest.approx(0)
    assert camera.center == pytest.approx((0.0, 0.0))


def test_a_bbox_with_another_aspect_fits_the_image_with_square_pixels():
    camera = camera_for_bbox(_bbox_3857(0, 0, 10, 10), 500, 250)

    assert camera.size[1] == 250
    assert abs(camera.size[0] - 250) < 5


@pytest.mark.parametrize(
    "lonlat", [(0, 0, 1, 40), (12.0, 41.0, 12.01, 43.0), (10.0, -80.0, 10.001, 80.0)]
)
def test_the_render_size_never_exceeds_the_image(lonlat):
    """A thin bbox would otherwise ask the renderer for a canvas of millions of rows."""
    camera = camera_for_bbox(_bbox_3857(*lonlat), 1024, 1024)

    assert 1 <= camera.size[0] <= 1024
    assert 1 <= camera.size[1] <= 1024


def test_a_request_needs_a_real_extent_and_size():
    with pytest.raises(ValueError, match="bbox"):
        MapRequest(bbox=(1, 0, 0, 1), width=10, height=10, style={})
    with pytest.raises(ValueError, match="width"):
        MapRequest(bbox=(0, 0, 1, 1), width=0, height=10, style={})


def test_a_request_does_not_print_its_style():
    """The style carries the signed archive URL, and a traceback prints reprs."""
    style = {"sources": {"archive": {"url": "pmtiles://bucket/a.pmtiles?X-Amz-Signature=SECRET"}}}
    request = MapRequest(bbox=(0, 0, 1, 1), width=1, height=1, style=style)

    assert "SECRET" not in repr(request)


def test_a_bbox_past_the_antimeridian_is_centred_within_the_world():
    from app.maps.camera import HALF_WORLD, camera_for_bbox

    bbox = (HALF_WORLD - 1_000_000.0, 0.0, HALF_WORLD + 3_000_000.0, 1_000_000.0)
    camera = camera_for_bbox(bbox, 512, 128)

    assert -180 <= camera.center[0] <= 180
    assert camera.center[0] == pytest.approx((HALF_WORLD + 1_000_000.0) / HALF_WORLD * 180 - 360)


def test_an_image_smaller_than_the_world_at_zoom_zero_is_drawn_at_zoom_zero():
    from app.maps.camera import HALF_WORLD, TILE_SIZE, camera_for_bbox

    world = (-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD)
    camera = camera_for_bbox(world, 500, 300)

    # Renderers take no zoom below 0: the render is larger and is scaled down.
    assert camera.zoom == 0
    assert camera.size == (TILE_SIZE, TILE_SIZE)


def test_a_bbox_smaller_than_zoom_24_shows_is_drawn_at_zoom_24():
    from app.maps.camera import camera_for_bbox

    camera = camera_for_bbox((1_400_000.0, 5_150_000.0, 1_400_002.0, 5_150_002.0), 1024, 1024)

    # Renderers take no zoom above 24: the render is smaller and is scaled up.
    assert camera.zoom == 24
    assert camera.size[0] < 1024 and camera.size == (camera.size[0], camera.size[0])
