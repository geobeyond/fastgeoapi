"""The generic tile provider: its bases, a backend composed in, and what it refuses.

Imports stay inside the tests: other modules purge ``app.*`` from
``sys.modules``, and the provider, the registry and the contract a test
uses must come from the same import.
"""

import asyncio
from unittest import mock

import pytest

SERVER = "http://localhost:5000/geoapi"
PNG = {"name": "png", "mimetype": "image/png"}


def _definition(data, format_=PNG, **options) -> dict:
    return {
        "type": "tile",
        "name": "app.provider.tiles.TilesProvider",
        "data": str(data),
        "options": {"zoom": {"min": 0, "max": 5}, "schemes": ["WebMercatorQuad"], **options},
        "format": format_,
    }


class _Grid:
    """A backend that needs no file: every tile says where it is, down to zoom 2."""

    format = "grid"

    def __init__(self, context):
        self.context = context

    def content(self):
        from app.tiles.contract import TileContent

        return TileContent(
            "map",
            "image/png",
            "png",
            0,
            2,
            (-180.0, -85.0511287, 180.0, 85.0511287),
            (0.0, 0.0, 0),
            name="world",
            tile_size=256,
        )

    async def acontent(self):
        return self.content()

    def tile(self, z, x, y):
        from app.tiles.contract import TileOutsideError

        if z > 2:
            raise TileOutsideError(f"zoom {z} is deeper than the grid")
        return f"{z}/{x}/{y}".encode()

    async def atile(self, z, x, y):
        return self.tile(z, x, y)


def test_the_tile_provider_is_one_line_of_bases_like_the_others():
    from pygeoapi.provider.tile import BaseTileProvider

    from app.provider.base import AsyncProviderMixin, StorageBackedMixin
    from app.provider.pmtiles import PMTilesProvider, PMTilesTiles
    from app.provider.tiles import TilesProvider

    assert TilesProvider.__bases__ == (AsyncProviderMixin, StorageBackedMixin, BaseTileProvider)
    assert PMTilesProvider.__bases__ == (TilesProvider,)
    assert PMTilesProvider.source_builder is PMTilesTiles


def test_another_backend_serves_tiles_by_composing_the_provider(tmp_path):
    from app.provider.tiles import TilesProvider
    from app.tiles import sources

    with mock.patch.dict(sources._REGISTRY):
        sources.register_tile_source(
            "grid", matches=lambda data: data.endswith(".grid"), build=_Grid
        )
        provider = TilesProvider(_definition(tmp_path / "world.grid"))

    assert provider.get_tiles(z=1, x=1, y=0) == b"1/1/0"
    assert asyncio.run(provider.aget_tiles(z=1, x=1, y=0)) == b"1/1/0"
    assert (
        provider.get_default_metadata(
            "world", SERVER, "world", "WebMercatorQuad", "World", "World", []
        )["dataType"]
        == "map"
    )
    assert provider.get_vendor_metadata(
        "world", SERVER, "world", "WebMercatorQuad", "World", "World", []
    )["tiles"] == [f"{SERVER}/collections/world/tiles/WebMercatorQuad/{{z}}/{{y}}/{{x}}?f=png"]


def test_outside_the_zooms_of_the_data_or_of_the_configuration_is_not_found(tmp_path):
    from pygeoapi.provider.tile import ProviderTileNotFoundError

    from app.provider.tiles import TilesProvider
    from app.tiles import sources

    with mock.patch.dict(sources._REGISTRY):
        sources.register_tile_source(
            "grid", matches=lambda data: data.endswith(".grid"), build=_Grid
        )
        provider = TilesProvider(_definition(tmp_path / "world.grid"))

    with pytest.raises(ProviderTileNotFoundError):
        provider.get_tiles(z=3, x=0, y=0)  # the grid stops at 2
    with pytest.raises(ProviderTileNotFoundError):
        provider.get_tiles(z=6, x=0, y=0)  # the configuration stops at 5


def test_data_no_backend_reads_is_refused_at_construction(tmp_path):
    from pygeoapi.provider.base import ProviderGenericError

    from app.provider.tiles import TilesProvider

    with pytest.raises(ProviderGenericError) as error:
        TilesProvider(_definition(tmp_path / "dem.tif"))
    assert (
        error.value.message
        == f"tile source not supported: no tile source reads {tmp_path / 'dem.tif'}"
    )


def test_an_unknown_dem_encoding_is_refused_before_any_read(tmp_path):
    from pygeoapi.provider.base import ProviderGenericError

    from app.provider.pmtiles import PMTilesProvider

    with pytest.raises(ProviderGenericError) as error:
        PMTilesProvider(_definition(tmp_path / "not-there.pmtiles", dem="srtm"))
    assert error.value.message == "options.dem must be one of terrarium, mapbox, not srtm"
