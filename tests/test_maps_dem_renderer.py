"""Elevations shaded by the real MapLibre Native renderer (the maps group, on Linux)."""

from __future__ import annotations

import io
import statistics

import pytest
from PIL import Image

from tests.maps_fixtures import map_provider
from tests.pmtiles_fixtures import terrarium_archive

pytestmark = pytest.mark.renderer
mlnative = pytest.importorskip("mlnative")
try:
    mlnative.get_binary_path()
except Exception:
    pytest.skip("the mlnative binary is missing", allow_module_level=True)

WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
# Around the fixture's cone: its slopes fill the middle, flat land the corners.
AROUND_THE_CONE = [-4_000_000.0, -4_000_000.0, 4_000_000.0, 4_000_000.0]
BACKGROUND = (242, 239, 233)  # the default hillshade style's background, #f2efe9
REAL = "app.maps.mlnative.create_renderer"


def _share(image: Image.Image, colour: tuple[int, int, int], tolerance: int = 8) -> float:
    data = image.tobytes()
    pixels = [tuple(data[i : i + 3]) for i in range(0, len(data), 3)]
    close = [
        p for p in pixels if all(abs(a - b) <= tolerance for a, b in zip(p, colour, strict=True))
    ]
    return len(close) / len(pixels)


@pytest.mark.asyncio
async def test_an_elevation_archive_is_shaded_by_the_real_renderer(tmp_path):
    from app.provider.maplibre import MapLibreMapProvider

    archive = terrarium_archive(tmp_path / "terrain.pmtiles")
    provider = MapLibreMapProvider(map_provider(archive, renderer=REAL, dem="terrarium"))
    try:
        png = await provider.aquery(
            bbox=AROUND_THE_CONE, width=256, height=256, crs=WEB_MERCATOR, transparent=False
        )
    finally:
        await provider.aclose()

    image = Image.open(io.BytesIO(png)).convert("RGB")
    # Flat land shows the background; drawn as a plain raster it would be the
    # dark red of the encoding, (128, 0, 0).
    assert _share(image, BACKGROUND) > 0.5
    # The slopes of the cone are shaded, so the greys spread.
    assert statistics.pstdev(image.convert("L").tobytes()) > 8
