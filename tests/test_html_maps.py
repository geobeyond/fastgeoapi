"""What a page's map shows first, and the configuration of its island.

``app.*`` is imported at the top of this module.
"""

import pytest

from app.html.maps import (
    MAP_IMAGE_MIN_ZOOM,
    basemap,
    camera,
    domain_footprint,
    extent_island,
    extent_of,
    features_island,
    footprint,
    image_island,
    tiles_island,
)
from app.provider.tile_styles import TileStyle

ROME = {"extents": {"spatial": {"bbox": [12.2, 41.7, 12.7, 42.1]}}}


@pytest.mark.parametrize(
    ("bbox", "expected"),
    [
        ([12.2, 41.7, 12.7, 42.1], [12.2, 41.7, 12.7, 42.1]),
        ([[12.2, 41.7, 12.7, 42.1], [0, 0, 1, 1]], [12.2, 41.7, 12.7, 42.1]),
        ([12.2, 41.7, 0, 12.7, 42.1, 100], [12.2, 41.7, 12.7, 42.1]),
    ],
)
def test_the_extent_is_the_first_box_in_two_dimensions(bbox, expected):
    assert extent_of({"extents": {"spatial": {"bbox": bbox}}}) == expected


def test_the_extent_of_the_collection_json_reads_the_same():
    assert extent_of({"extent": {"spatial": {"bbox": [[1, 2, 3, 4]]}}}) == [1.0, 2.0, 3.0, 4.0]


def test_a_collection_without_extent_has_none():
    assert extent_of({}) is None


def test_the_configured_view_comes_first():
    resource = {**ROME, "view": {"center": [12.5, 41.9], "zoom": 1}}

    assert camera(resource, tilejson_center=(10.0, 45.0, 5)) == {
        "center": [12.5, 41.9],
        "zoom": 1.0,
        "minZoom": 0,
    }
    assert camera(resource, map_image=True)["zoom"] == MAP_IMAGE_MIN_ZOOM


def test_then_the_tilejson_center_when_it_is_somewhere():
    assert camera(ROME, tilejson_center=(12.4, 41.8, 9)) == {
        "center": [12.4, 41.8],
        "zoom": 9.0,
        "minZoom": 0,
    }


def test_a_tilejson_center_at_zero_falls_back_to_the_extent():
    assert camera(ROME, tilejson_center=(0.0, 0.0, 0)) == {
        "bounds": [12.2, 41.7, 12.7, 42.1],
        "minZoom": 0,
    }


def test_a_tilejson_center_at_zoom_zero_falls_back_to_the_extent():
    # At zoom 0 the whole world is in view: such a center says nothing of
    # where the data is, and a small archive would open as an invisible dot.
    assert camera(ROME, tilejson_center=(12.45, 41.9, 0)) == {
        "bounds": [12.2, 41.7, 12.7, 42.1],
        "minZoom": 0,
    }


def test_map_images_never_open_below_zoom_two():
    assert camera(ROME, map_image=True)["minZoom"] == MAP_IMAGE_MIN_ZOOM


def test_a_map_of_data_fits_the_data_and_keeps_the_extent_as_fallback():
    assert camera(ROME, fit_data=True) == {
        "bounds": [12.2, 41.7, 12.7, 42.1],
        "fitData": True,
        "minZoom": 0,
    }


def test_without_anything_the_map_shows_the_world():
    assert camera({}) == {"center": [0.0, 0.0], "zoom": 0.0, "minZoom": 0}


def test_the_basemap_is_pygeoapis_own():
    config = {
        "server": {"map": {"url": "https://tiles.example/{z}/{x}/{y}.png", "attribution": "OSM"}}
    }

    assert basemap(config) == {
        "url": "https://tiles.example/{z}/{x}/{y}.png",
        "attribution": "OSM",
    }
    assert basemap({"server": {}}) is None
    styled = {"server": {"map": {**config["server"]["map"], "style": "https://s/liberty"}}}
    assert basemap(styled) == {
        "url": "https://tiles.example/{z}/{x}/{y}.png",
        "attribution": "OSM",
        "style": "https://s/liberty",
    }


def test_the_islands_say_what_they_draw():
    view = {"bounds": [0, 0, 1, 1], "minZoom": 0}
    styles = [TileStyle(None, {"version": 8}), TileStyle("night", {"version": 8, "name": "n"})]

    osm = {"url": "https://t/{z}/{x}/{y}.png", "attribution": "OSM"}
    assert tiles_island(view, osm, styles, "Default", "Style") == {
        "kind": "tiles",
        "camera": view,
        "basemap": osm,
        "styles": [
            {"name": "Default", "style": {"version": 8}},
            {"name": "night", "style": {"version": 8, "name": "n"}},
        ],
        "labels": {"style": "Style"},
    }
    maps = [{"name": "Default", "url": "https://e.org/map"}]
    assert image_island(view, None, maps, 1024, "Style") == {
        "kind": "image",
        "camera": view,
        "basemap": None,
        "maps": maps,
        "maxSize": 1024,
        "labels": {"style": "Style"},
    }
    items = "https://e.org/items?f=json"
    assert features_island(view, None, items)["data"] == items
    assert extent_island(view, None, [0, 0, 1, 1])["bbox"] == [0, 0, 1, 1]


def test_the_footprint_is_the_geometry_or_else_the_bbox():
    point = {"type": "Point", "coordinates": [12.5, 41.9]}

    assert footprint({"geometry": point}) == {
        "type": "Feature",
        "properties": {},
        "geometry": point,
    }
    boxed = footprint({"geometry": None, "bbox": [12, 41, 13, 42]})
    assert boxed is not None
    assert boxed["geometry"] == {
        "type": "Polygon",
        "coordinates": [[[12, 41], [13, 41], [13, 42], [12, 42], [12, 41]]],
    }
    assert footprint({"geometry": None, "bbox": None}) is None


def test_a_point_domain_is_its_point_and_a_grid_its_box():
    point = {"axes": {"x": {"values": [12.5]}, "y": {"values": [41.9]}}}
    grid = {
        "axes": {
            "x": {"start": 12.0, "stop": 12.5, "num": 5},
            "y": {"start": 42.0, "stop": 41.6, "num": 4},
        }
    }

    at_point, over_grid = domain_footprint(point), domain_footprint(grid)
    assert at_point is not None
    assert over_grid is not None
    assert at_point["geometry"] == {"type": "Point", "coordinates": [12.5, 41.9]}
    assert over_grid["geometry"]["coordinates"] == [
        [[12.0, 41.6], [12.5, 41.6], [12.5, 42.0], [12.0, 42.0], [12.0, 41.6]]
    ]


def test_a_domain_without_x_and_y_draws_nothing():
    assert domain_footprint({"axes": {"t": {"values": ["2026-10-03"]}}}) is None
