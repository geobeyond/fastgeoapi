"""Maps drawn by the real MapLibre Native renderer (the maps group, on Linux)."""

from __future__ import annotations

import io
import os
import signal

import pytest
from PIL import Image

from tests.maps_fixtures import map_provider
from tests.mvt_fixtures import land_archive

pytestmark = pytest.mark.renderer
mlnative = pytest.importorskip("mlnative")
try:
    mlnative.get_binary_path()
except Exception:
    pytest.skip("the mlnative binary is missing", allow_module_level=True)

ROME = [1379000.0, 5140000.0, 1403000.0, 5160000.0]  # EPSG:3857 metres
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
# The default style fills the first layer with #e15759 at 0.3 over white.
OPAQUE = (246, 205, 205)
REAL = "app.maps.mlnative.create_renderer"


def _share(png: bytes, colour: tuple[int, ...], tolerance: int = 8) -> float:
    image = Image.open(io.BytesIO(png)).convert("RGBA" if len(colour) == 4 else "RGB")
    data, size = image.tobytes(), len(image.getbands())
    pixels = [tuple(data[i : i + size]) for i in range(0, len(data), size)]
    close = [
        p for p in pixels if all(abs(a - b) <= tolerance for a, b in zip(p, colour, strict=True))
    ]
    return len(close) / len(pixels)


@pytest.fixture
def archive(tmp_path):
    return land_archive(tmp_path / "land.pmtiles")


def _provider(definition):
    from app.provider.maplibre import MapLibreMapProvider

    return MapLibreMapProvider(definition)


async def _map(provider, **kwargs):
    args = {"bbox": ROME, "width": 256, "height": 256, "crs": WEB_MERCATOR, "transparent": False}
    return await provider.aquery(**{**args, **kwargs})


def _request(archive, width, height, transparent=False):
    from app.maps.contract import MapRequest
    from app.maps.sources import ObjectUrl, PMTilesSource
    from app.maps.styles import MapLibreStyles

    data = archive.read_bytes()
    source = PMTilesSource(ObjectUrl(local_path=archive), lambda o, n: data[o : o + n])
    style = MapLibreStyles(source).style(None, transparent=transparent)
    return MapRequest(bbox=tuple(ROME), width=width, height=height, style=style)


@pytest.mark.asyncio
async def test_a_map_of_the_archive_has_the_requested_size_and_the_layer_colour(archive):
    provider = _provider(map_provider(archive, renderer=REAL))
    try:
        png = await _map(provider)
    finally:
        await provider.aclose()

    assert Image.open(io.BytesIO(png)).size == (256, 256)
    assert _share(png, OPAQUE) > 0.9


@pytest.mark.asyncio
async def test_a_transparent_map_after_an_opaque_one_drops_the_background(archive):
    provider = _provider(map_provider(archive, renderer=REAL))
    try:
        await _map(provider)
        png = await _map(provider, transparent=True)
    finally:
        await provider.aclose()

    alphas = Image.open(io.BytesIO(png)).convert("RGBA").tobytes()[3::4]
    assert sum(60 <= a <= 95 for a in alphas) / len(alphas) > 0.9  # 0.3 of 255, no white under it


@pytest.mark.asyncio
async def test_a_wide_image_of_a_square_bbox_is_stretched(archive):
    provider = _provider(map_provider(archive, renderer=REAL))
    try:
        png = await _map(provider, width=300, height=100)
    finally:
        await provider.aclose()

    assert Image.open(io.BytesIO(png)).size == (300, 100)
    assert _share(png, OPAQUE) > 0.9


@pytest.mark.asyncio
async def test_one_process_draws_every_size(archive):
    from app.maps.mlnative import create_renderer

    renderer = create_renderer({})
    try:
        sizes, pids = [], []
        for width, height in [(64, 64), (512, 384), (1024, 1024)]:
            png = await renderer.render(_request(archive, width, height))
            sizes.append(Image.open(io.BytesIO(png)).size)
            pids.append(renderer.pid)
    finally:
        await renderer.aclose()

    assert sizes == [(64, 64), (512, 384), (1024, 1024)]
    assert len(set(pids)) == 1
    assert _share(png, OPAQUE) > 0.9


@pytest.mark.asyncio
async def test_a_process_above_max_rss_is_replaced(archive):
    from app.maps.mlnative import create_renderer

    renderer = create_renderer({"max_rss_mb": 1})
    try:
        await renderer.render(_request(archive, 64, 64))
        assert renderer.pid is None
        await renderer.render(_request(archive, 64, 64))
    finally:
        await renderer.aclose()


@pytest.mark.asyncio
async def test_a_killed_process_is_replaced_at_the_next_map(archive):
    from app.maps.contract import RenderError
    from app.maps.mlnative import create_renderer

    renderer = create_renderer({})
    try:
        await renderer.render(_request(archive, 64, 64))
        os.kill(renderer.pid, signal.SIGKILL)
        with pytest.raises(RenderError):
            await renderer.render(_request(archive, 64, 64))
        png = await renderer.render(_request(archive, 64, 64))
    finally:
        await renderer.aclose()

    assert _share(png, OPAQUE) > 0.9


@pytest.mark.asyncio
async def test_a_presigned_url_on_the_local_s3_is_drawn(archive, s3_endpoint, monkeypatch):
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setenv("AWS_ALLOW_HTTP", "true")
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket="fastgeoapi-maps")
    client.upload_file(str(archive), "fastgeoapi-maps", "tiles/land.pmtiles")
    definition = map_provider(archive, renderer=REAL)
    definition["data"] = "s3://fastgeoapi-maps/tiles/land.pmtiles"
    definition["store_options"] = {
        "endpoint": s3_endpoint.removeprefix("http://"),
        "region": "us-east-1",
        "key_id": "test",
        "secret": "test",
        "url_style": "path",
        "use_ssl": False,
    }
    provider = _provider(definition)
    try:
        png = await _map(provider)
    finally:
        await provider.aclose()

    assert _share(png, OPAQUE) > 0.9


@pytest.mark.asyncio
async def test_no_blocking_call_reaches_the_loop_while_a_map_is_drawn(archive):
    from blockbuster import blockbuster_ctx

    provider = _provider(map_provider(archive, renderer=REAL))
    try:
        with blockbuster_ctx():
            png = await _map(provider)
    finally:
        await provider.aclose()

    assert _share(png, OPAQUE) > 0.9


@pytest.mark.asyncio
async def test_the_whole_world_in_a_small_image_is_drawn(archive):
    from app.maps.camera import HALF_WORLD

    # Smaller than the world at zoom 0, as a map asked for without a bbox.
    provider = _provider(map_provider(archive, renderer=REAL))
    try:
        world = [-HALF_WORLD, -HALF_WORLD, HALF_WORLD, HALF_WORLD]
        png = await _map(provider, bbox=world, width=500, height=300)
    finally:
        await provider.aclose()

    assert Image.open(io.BytesIO(png)).size == (500, 300)
    assert _share(png, OPAQUE) > 0.9
