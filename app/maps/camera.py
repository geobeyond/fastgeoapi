"""Where to point a map camera so that an EPSG:3857 bbox fills the image.

A camera is a centre in longitude and latitude and a zoom, the way web
map renderers position a view; the zoom counts tiles of ``TILE_SIZE``
pixels. The centre is the Mercator midpoint of the bbox: the mean of the
two latitudes would move it towards the equator. A renderer that takes
an extent and a size directly needs only the render size.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TILE_SIZE = 512
"""The tile size the zoom counts.

512 pixels is the convention of MapLibre and the other GL renderers. The
OGC WebMercatorQuad tile matrix set and XYZ raster tiles count 256, so
the same scale is one zoom level higher there. It is a constant because
MapLibre is the only renderer today; one that counts 256 makes it a
parameter of :func:`camera_for_bbox`.
"""

HALF_WORLD = 20037508.342789244
"""Half the width of the EPSG:3857 world, in metres."""

MAX_ZOOM = 24
"""The highest zoom MapLibre and the other GL renderers take."""


@dataclass(frozen=True, slots=True)
class Camera:
    """A camera, and the size to render at so that pixels stay square."""

    center: tuple[float, float]
    zoom: float
    size: tuple[int, int]


def _y_to_lat(y: float) -> float:
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))


def _snap(value: float, limit: int) -> int:
    size = max(1, min(limit, round(value)))
    return limit if abs(size - limit) <= 1 else size


def camera_for_bbox(bbox: tuple[float, float, float, float], width: int, height: int) -> Camera:
    """The camera that shows ``bbox`` within a ``width`` by ``height`` image.

    Pixels stay square, so when the aspect of the bbox differs from the
    image's, the bbox fills one side and ``size`` is the smaller render
    that shows all of it. The caller resamples it to ``width`` by
    ``height``, the stretch a WMS GetMap makes. The render is never
    larger than the image, except below zoom 0: renderers take no lower
    zoom, so a bbox wider than the image at zoom 0 is drawn at zoom 0 and
    scaled down. Above ``MAX_ZOOM`` it is drawn at ``MAX_ZOOM``, smaller,
    and scaled up.
    """
    xmin, ymin, xmax, ymax = bbox
    world = 2 * HALF_WORLD
    x0, x1 = (xmin + HALF_WORLD) / world, (xmax + HALF_WORLD) / world
    y0, y1 = (HALF_WORLD - ymax) / world, (HALF_WORLD - ymin) / world
    dx, dy = x1 - x0, y1 - y0
    scale = min(width / dx, height / dy)  # pixels per world width
    zoom = math.log2(scale / TILE_SIZE)
    # A bbox past the antimeridian has its centre beyond 180°. Renderers draw
    # the world again there, so the centre is wrapped back within ±180°.
    lon = ((xmin + xmax) / 2 / HALF_WORLD * 180.0 + 180.0) % 360.0 - 180.0
    lat = _y_to_lat((y0 + y1) / 2)
    if not 0 <= zoom <= MAX_ZOOM:
        zoom = min(max(zoom, 0.0), float(MAX_ZOOM))
        scale = TILE_SIZE * 2**zoom
        size = (max(1, round(dx * scale)), max(1, round(dy * scale)))
        return Camera(center=(lon, lat), zoom=zoom, size=size)
    return Camera(
        center=(lon, lat),
        zoom=zoom,
        size=(_snap(dx * scale, width), _snap(dy * scale, height)),
    )
