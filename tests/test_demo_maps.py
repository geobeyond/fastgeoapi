"""The demo draws its Lazio roads archive as a map, read at its public address."""

from pathlib import Path

import pytest


@pytest.fixture
def providers():
    from pygeoapi.util import yaml_load

    config = yaml_load(Path("pygeoapi-config.demo.yml").open())
    return config["resources"]["lazio-roads-tiles"]["providers"]


def test_the_lazio_roads_tiles_have_a_map_on_the_same_archive(providers):
    (map_provider,) = [p for p in providers if p["type"] == "map"]
    tiles = next(p for p in providers if p["type"] == "tile")

    assert map_provider["name"] == "app.provider.maplibre.MapLibreMapProvider"
    assert map_provider["data"] == tiles["data"]
    assert map_provider["storage_crs"] == "http://www.opengis.net/def/crs/EPSG/0/3857"
    assert map_provider["options"]["data_url"] == (
        "https://fastgeoapi-demo.fly.storage.tigris.dev/tiles/lazio-roads.pmtiles"
    )


def test_the_demo_map_provider_is_built_without_touching_the_network(providers):
    from app.provider.maplibre import MapLibreMapProvider

    (map_provider,) = [p for p in providers if p["type"] == "map"]
    provider = MapLibreMapProvider(map_provider)

    assert not provider.renderer_is_built
