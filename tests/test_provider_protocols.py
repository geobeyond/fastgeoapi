"""Capability Protocols: structure decides, not descent (ADR-0010, decision 4)."""

from app.interfaces import AsyncFeatureProvider, AsyncTileProvider
from app.provider.base import AsyncProviderMixin


class _TileRoot:
    def __init__(self, provider_def):
        self.format_type = provider_def["format"]["name"]

    def get_layer(self):
        return "layer"

    def get_tiles(self, **kwargs):
        return b""


class _NativeTiles(AsyncProviderMixin, _TileRoot):
    native_async = True

    async def aget_tiles(self, layer, tileset, z, y, x, format_):
        return b"\x00"


class _ThreadedTiles(AsyncProviderMixin, _TileRoot):
    """No twin written: the router must fall back to the threadpool."""


class _FeatureRoot:
    def __init__(self, provider_def):
        self.name = provider_def["name"]

    def query(self, **kwargs):
        return {}

    def get(self, identifier, **kwargs):
        return {}


class _NativeFeatures(AsyncProviderMixin, _FeatureRoot):
    native_async = True

    async def aquery(self, **kwargs):
        return {}

    async def aget(self, identifier, **kwargs):
        return {}


class _ThreadedFeatures(AsyncProviderMixin, _FeatureRoot):
    pass


DEF = {"name": "x", "format": {"name": "pbf"}}


def test_a_native_tile_provider_conforms_by_structure():
    assert isinstance(_NativeTiles(DEF), AsyncTileProvider)


def test_without_the_twin_there_is_no_tile_capability():
    assert not isinstance(_ThreadedTiles(DEF), AsyncTileProvider)


def test_a_foreign_object_with_the_members_conforms_too():
    class Foreign:
        native_async = True
        format_type = "pbf"

        def get_layer(self):
            return None

        async def aget_tiles(self, layer, tileset, z, y, x, format_):
            return None

    assert isinstance(Foreign(), AsyncTileProvider)


def test_feature_capability_needs_both_twins():
    assert isinstance(_NativeFeatures(DEF), AsyncFeatureProvider)
    assert not isinstance(_ThreadedFeatures(DEF), AsyncFeatureProvider)
