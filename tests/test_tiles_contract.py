"""The contract between the tile provider and the backends, and the registry that picks them.

Imports stay inside the tests: other modules purge ``app.*`` from
``sys.modules``, and the registry and the sources a test uses must come
from the same import.
"""

import re
from unittest import mock

import pytest


def test_the_data_type_comes_from_the_configuration():
    from app.tiles.contract import data_type_for

    assert data_type_for("application/vnd.mapbox-vector-tile", None) == "vector"
    assert data_type_for(None, None) == "vector"
    assert data_type_for("image/webp", None) == "map"
    assert data_type_for("image/png", "terrarium") == "coverage"


def test_the_links_carry_the_f_value_of_their_media_type():
    from app.tiles.contract import format_parameter

    assert format_parameter("image/jpeg") == "jpg"
    assert format_parameter("application/x-protobuf") == "mvt"
    assert format_parameter(None) == "mvt"


def test_the_registry_picks_pmtiles_for_a_pmtiles_archive():
    from app.tiles.sources import tile_source_for

    assert tile_source_for("s3://bucket/tiles/places.pmtiles").format == "pmtiles"
    assert tile_source_for("/data/Roads.PMTILES").format == "pmtiles"


def test_data_no_backend_reads_is_a_lookup_error():
    from app.tiles.sources import tile_source_for

    with pytest.raises(LookupError, match=re.escape("no tile source reads /data/dem.tif")):
        tile_source_for("/data/dem.tif")


def test_a_registered_backend_is_found_by_its_data():
    from app.tiles import sources

    def build(context):
        raise AssertionError("the registry must not build the source")

    with mock.patch.dict(sources._REGISTRY):
        sources.register_tile_source(
            "grid", matches=lambda data: data.endswith(".grid"), build=build
        )
        registered = sources.tile_source_for("/data/world.grid")

    assert (registered.format, registered.build) == ("grid", build)


def test_a_source_that_answers_the_four_calls_is_a_tile_source():
    from app.tiles.contract import TileContent, TileSource

    class Grid:
        format = "grid"

        def content(self):
            return TileContent(
                "map", "image/png", "png", 0, 2, (-180.0, -85.0, 180.0, 85.0), (0.0, 0.0, 0)
            )

        async def acontent(self):
            return self.content()

        def tile(self, z, x, y):
            return b""

        async def atile(self, z, x, y):
            return b""

    assert isinstance(Grid(), TileSource)
