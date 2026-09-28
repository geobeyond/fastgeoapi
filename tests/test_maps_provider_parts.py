"""The parts every map provider composes, and the MapLibre provider made of them."""

import pytest
from pygeoapi.provider.base import BaseProvider

from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from tests.maps_fixtures import FakeRenderer, create_fake_renderer, map_provider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive

ROME = [1379000.0, 5140000.0, 1403000.0, 5160000.0]  # EPSG:3857 metres
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"


@pytest.fixture(autouse=True)
def _fresh_fakes():
    FakeRenderer.instances.clear()
    yield
    FakeRenderer.instances.clear()


class PlainMapProvider(AsyncProviderMixin, StorageBackedMixin, BaseProvider):
    """A family that is not MapLibre, whose style is the name of its data."""

    native_async = True

    def __init__(self, provider_def):
        from app.maps.queue import RenderQueue

        super().__init__(provider_def)
        self._queue = RenderQueue(
            lambda: create_fake_renderer({}), size=8, timeout=5.0, render_limit=20.0
        )

    def _style(self, name, transparent):
        if name is not None:
            raise KeyError(name)
        return {"data": self.provider_def["data"]}

    async def aquery(self, **kwargs):
        from app.provider.maps import draw_map, map_request

        request = map_request(self._style, max_size=32, **kwargs)
        return await draw_map(self._queue, request)


def test_the_maplibre_provider_is_one_line_of_bases_like_the_others():
    # Imported here, not at the top: tests that purge `app.*` from sys.modules
    # re-import the mixins, and the provider inherits from the new ones.
    from app.provider.base import AsyncProviderMixin, StorageBackedMixin
    from app.provider.maplibre import MapLibreMapProvider

    assert MapLibreMapProvider.__bases__ == (AsyncProviderMixin, StorageBackedMixin, BaseProvider)


@pytest.mark.asyncio
async def test_another_family_draws_by_composing_the_same_parts(tmp_path):
    from app.interfaces.providers import AsyncMapProvider

    provider = PlainMapProvider(map_provider(tmp_path / "roads.bin"))

    png = await provider.aquery(bbox=ROME, width=16, height=16, crs=WEB_MERCATOR)

    assert isinstance(provider, AsyncMapProvider)
    assert png.startswith(b"\x89PNG")
    assert FakeRenderer.instances[0].requests[0].style == {"data": str(tmp_path / "roads.bin")}


@pytest.mark.asyncio
async def test_another_family_keeps_the_limits_and_errors_of_the_parts(tmp_path):
    from app.provider.maps import MapParameterError, MapTooLargeError

    provider = PlainMapProvider(map_provider(tmp_path / "roads.bin"))

    with pytest.raises(MapTooLargeError):
        await provider.aquery(bbox=ROME, width=64, height=16, crs=WEB_MERCATOR)
    with pytest.raises(MapParameterError):
        await provider.aquery(bbox=ROME, width=16, height=16, crs="EPSG:4326")


def test_the_maplibre_provider_declares_the_maps_conformance_of_the_parts(tmp_path):
    from app.provider.maplibre import MapLibreMapProvider
    from app.provider.maps import MAPS_CONFORMANCE

    archive = write_archive(tmp_path / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})

    assert MapLibreMapProvider(map_provider(archive)).conformance_classes == MAPS_CONFORMANCE
