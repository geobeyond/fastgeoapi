"""What the map of a page shows first, and the configuration of its island."""

from __future__ import annotations

from typing import Any

from pygeoapi.formats import F_JSON

from app.html.pages import with_query, without_query
from app.provider.tile_styles import TileStyle

LONGITUDE_FIRST = frozenset(
    {
        "http://www.opengis.net/def/crs/OGC/1.3/CRS84",
        "http://www.opengis.net/def/crs/OGC/1.3/CRS84h",
    }
)
"""The reference systems MapLibre can draw as they are: longitude, then latitude."""

MAP_IMAGE_MIN_ZOOM = 2
"""The lowest zoom of a collection drawn as map images: a whole-world image can time out."""

DEFAULT_MAX_SIZE = 2048
"""The widest map image a page asks for, when the map provider sets no ``max_size``."""


def extent_of(resource: dict[str, Any]) -> list[float] | None:
    """West, south, east and north of the first spatial extent.

    ``resource`` is a collection's configuration (``extents``) or its JSON
    (``extent``).
    """
    extents = resource.get("extents") or resource.get("extent") or {}
    bbox = (extents.get("spatial") or {}).get("bbox")
    if not bbox:
        return None
    first = bbox[0] if isinstance(bbox[0], list) else bbox
    if len(first) == 6:
        first = [first[0], first[1], first[3], first[4]]
    return [float(value) for value in first[:4]]


def camera(
    resource: dict[str, Any],
    *,
    tilejson_center: tuple[float, float, float] | None = None,
    map_image: bool = False,
    fit_data: bool = False,
) -> dict[str, Any]:
    """Where a map opens: the collection's ``view``, the tiles' center, its extent, the world."""
    floor = MAP_IMAGE_MIN_ZOOM if map_image else 0
    view = resource.get("view")
    if view:
        return {
            "center": list(view["center"]),
            "zoom": max(float(view["zoom"]), floor),
            "minZoom": floor,
        }
    # At zoom 0 the whole world is in view, so such a center says nothing of
    # where the data is: the extent does.
    if tilejson_center is not None and any(tilejson_center[:2]) and tilejson_center[2] > 0:
        lon, lat, zoom = tilejson_center
        return {"center": [lon, lat], "zoom": max(float(zoom), floor), "minZoom": floor}
    found: dict[str, Any] = {"minZoom": floor}
    if fit_data:
        found["fitData"] = True
    bbox = extent_of(resource)
    if bbox is not None:
        found["bounds"] = bbox
    else:
        found.update(center=[0.0, 0.0], zoom=float(floor))
    return found


def basemap(config: dict[str, Any]) -> dict[str, str] | None:
    """The background map of pygeoapi's configuration, drawn under the data."""
    found = (config.get("server") or {}).get("map") or {}
    if not found.get("url"):
        return None
    base = {"url": found["url"], "attribution": found.get("attribution", "")}
    if found.get("style"):
        # A MapLibre style the pages draw on; the tiles of ``url`` stay as a fallback.
        base["style"] = found["style"]
    return base


def tiles_island(
    view: dict[str, Any],
    base: dict[str, str] | None,
    styles: list[TileStyle],
    default_name: str,
    style_label: str,
) -> dict[str, Any]:
    """A map of the collection's tiles over the basemap, with every style it can be drawn with."""
    return {
        "kind": "tiles",
        "camera": view,
        "basemap": base,
        "styles": [
            {"name": style.name or default_name, "style": style.document} for style in styles
        ],
        "labels": {"style": style_label},
    }


def image_island(
    view: dict[str, Any],
    base: dict[str, str] | None,
    maps: list[dict[str, str]],
    max_size: int,
    style_label: str,
) -> dict[str, Any]:
    """A map of images the collection's map provider draws, one for each view."""
    return {
        "kind": "image",
        "camera": view,
        "basemap": base,
        "maps": maps,
        "maxSize": max_size,
        "labels": {"style": style_label},
    }


def drawn_features(
    page_url: str, crs: str | None, features: dict[str, Any]
) -> dict[str, Any] | str:
    """What a map of features draws: the page's features, or its JSON without ``crs``.

    MapLibre reads longitude and latitude. A page asked in another
    reference system draws the same document asked in CRS84.
    """
    if not crs or crs in LONGITUDE_FIRST:
        return features
    return with_query(without_query(page_url, "crs"), f=F_JSON)


def features_island(view: dict[str, Any], base: dict[str, str] | None, data: Any) -> dict[str, Any]:
    """A map of GeoJSON features: inline, or the URL of a page of items."""
    return {"kind": "features", "camera": view, "basemap": base, "data": data}


def extent_island(
    view: dict[str, Any], base: dict[str, str] | None, bbox: list[float]
) -> dict[str, Any]:
    """A map of a box, for a collection with nothing else to draw."""
    return {"kind": "extent", "camera": view, "basemap": base, "bbox": bbox}


def _box(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def footprint(document: dict[str, Any]) -> dict[str, Any] | None:
    """A GeoJSON feature of where a document lies: its geometry, or else its bbox."""
    geometry = document.get("geometry")
    if geometry:
        return {"type": "Feature", "properties": {}, "geometry": geometry}
    bbox = document.get("bbox")
    if not bbox or len(bbox) < 4:
        return None
    if len(bbox) == 6:
        return _box(bbox[0], bbox[1], bbox[3], bbox[4])
    return _box(*bbox[:4])


def _axis_range(axis: dict[str, Any]) -> tuple[float, float] | None:
    if axis.get("values"):
        values = [float(value) for value in axis["values"]]
        return min(values), max(values)
    if "start" in axis and "stop" in axis:
        return min(axis["start"], axis["stop"]), max(axis["start"], axis["stop"])
    return None


def domain_footprint(domain: dict[str, Any]) -> dict[str, Any] | None:
    """A GeoJSON feature of a CoverageJSON domain: its point, or the box of its x and y."""
    axes = domain.get("axes") or {}
    if "x" not in axes or "y" not in axes:
        return None
    x, y = _axis_range(axes["x"]), _axis_range(axes["y"])
    if x is None or y is None:
        return None
    if x[0] == x[1] and y[0] == y[1]:
        return {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": [x[0], y[0]]},
        }
    return _box(x[0], y[0], x[1], y[1])
