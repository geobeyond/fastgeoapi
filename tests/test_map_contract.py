"""The contract a native map provider meets, and the configurations that break it.

``app.*`` is imported inside the tests, nowhere else. The two providers below
are loaded by their dotted path, as a configuration names them.
"""

import re

import pytest
from pygeoapi.provider.base import BaseProvider

from tests.maps_fixtures import map_provider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config


class NoVersion(BaseProvider):
    """A native map provider without ``aversion``."""

    native_async = True

    async def aquery(self, **kwargs):
        return b""

    @property
    def limits(self):
        return None

    def close(self):
        """Nothing to release."""


class Threaded(BaseProvider):
    """A map provider pygeoapi calls in its threadpool."""

    def query(self, **kwargs):
        return b""


def _definition(name: str) -> dict:
    return {
        "type": "map",
        "name": name,
        "data": "unused",
        "storage_crs": "http://www.opengis.net/def/crs/EPSG/0/3857",
        "format": {"name": "png", "mimetype": "image/png"},
    }


def _archive(tmp_path):
    return write_archive(
        tmp_path / "roads.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "roads", "vector_layers": [{"id": "roads"}]},
    )


def test_a_native_map_provider_without_aversion_is_refused():
    from app.pygeoapi.factory import ConfigValidationError, normalize_config

    config = _config(
        {"lakes": _collection("Lakes", [_definition("tests.test_map_contract.NoVersion")])}
    )
    message = (
        "configuration at resources.lakes.providers.0: "
        "tests.test_map_contract.NoVersion sets native_async but has no aversion"
    )

    with pytest.raises(ConfigValidationError, match=re.escape(message)):
        normalize_config(config)


def test_the_maplibre_provider_meets_the_contract(tmp_path):
    import pygeoapi.plugin

    from app.interfaces.providers import AsyncMapProvider
    from app.pygeoapi.factory import normalize_config

    definition = map_provider(_archive(tmp_path))
    normalize_config(_config({"roads": _collection("Roads", [definition])}))

    assert isinstance(pygeoapi.plugin.load_plugin("provider", definition), AsyncMapProvider)


def test_a_map_provider_that_is_not_native_is_left_to_pygeoapi():
    from app.pygeoapi.api_async.maps import native_map_provider
    from app.pygeoapi.factory import build_api, build_openapi, normalize_config

    config = _config(
        {"lakes": _collection("Lakes", [_definition("tests.test_map_contract.Threaded")])}
    )
    normalize_config(config)

    assert native_map_provider(build_api(config, build_openapi(config)), "lakes") is None


def test_the_maplibre_limits_come_from_its_options(tmp_path):
    from app.interfaces.providers import MapLimits
    from app.provider.maplibre import MapLibreMapProvider

    provider = MapLibreMapProvider(
        map_provider(_archive(tmp_path), max_size=1024, queue=3, timeout=12)
    )

    assert provider.limits == MapLimits(1024, 1024, None, 1, 3, 12.0)


def test_the_map_family_protocol_is_exported():
    import app.interfaces
    import app.interfaces.providers

    assert app.interfaces.AsyncMapProvider is app.interfaces.providers.AsyncMapProvider
