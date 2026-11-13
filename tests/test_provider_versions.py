"""The version of a tile provider's answer, known before a tile is read.

``app.*`` is imported inside the tests, as in the range cache tests, so
each test gets the classes in ``sys.modules`` even after another module
purged ``app.*``.
"""

import gzip
import os
import shutil

import pytest

from tests.pmtiles_fixtures import write_archive
from tests.range_cache_fixtures import Clock, CountingStore, memory_store, range_cache
from tests.test_cached_ranges_revalidation import _settled

DATA = "s3://bucket/tiles/roads.pmtiles"
KEY = "roads.pmtiles"
MVT = "application/vnd.mapbox-vector-tile"


def _definition(data, **options):
    return {
        "type": "tile",
        "name": "app.provider.pmtiles.PMTilesProvider",
        "data": str(data),
        "options": {"zoom": {"min": 0, "max": 2}, "schemes": ["WebMercatorQuad"], **options},
        "format": {"name": "pbf", "mimetype": MVT},
    }


def _provider(definition):
    from app.provider.pmtiles import PMTilesProvider

    return PMTilesProvider(definition)


def _archive(path, label=b"tile"):
    return write_archive(path, {(0, 0, 0): gzip.compress(label + b" 0/0/0")})


def test_a_tile_provider_is_a_versioned_provider(tmp_path):
    from app.interfaces.providers import VersionedProvider

    provider = _provider(_definition(_archive(tmp_path / "roads.pmtiles")))

    assert isinstance(provider, VersionedProvider)


@pytest.mark.asyncio
async def test_two_providers_of_one_definition_give_one_version(tmp_path):
    definition = _definition(_archive(tmp_path / "roads.pmtiles"))

    first = await _provider(definition).aversion(z=0, y=0, x=0)
    second = await _provider(dict(definition)).aversion(z=0, y=0, x=0)

    assert first is not None
    assert first == second


@pytest.mark.asyncio
async def test_a_local_archive_written_again_gives_a_new_version(tmp_path):
    path = _archive(tmp_path / "roads.pmtiles")
    provider = _provider(_definition(path))
    before = await provider.aversion(z=0, y=0, x=0)

    _archive(path, label=b"a longer tile")
    later = path.stat().st_mtime + 10
    os.utime(path, (later, later))

    assert await provider.aversion(z=0, y=0, x=0) != before


@pytest.mark.asyncio
async def test_a_copy_with_the_same_size_and_time_has_the_same_data_version(tmp_path):
    """Each machine running one image holds such a copy, with an inode of its own.

    The local store's ETag names the inode, so it differs from machine to machine.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    original = _archive(tmp_path / "a" / "roads.pmtiles")
    copy = tmp_path / "b" / "roads.pmtiles"
    shutil.copy2(original, copy)

    first = await _provider(_definition(original)).adata_version()
    second = await _provider(_definition(copy)).adata_version()

    assert first == second


@pytest.mark.asyncio
async def test_another_definition_gives_another_version(tmp_path):
    path = _archive(tmp_path / "roads.pmtiles")

    narrow = await _provider(_definition(path)).aversion(z=0, y=0, x=0)
    wide = await _provider(_definition(path, zoom={"min": 0, "max": 3})).aversion(z=0, y=0, x=0)

    assert narrow != wide


@pytest.mark.asyncio
async def test_a_tile_outside_the_limits_has_no_version(tmp_path):
    provider = _provider(_definition(_archive(tmp_path / "roads.pmtiles")))

    assert await provider.aversion(z=5, y=0, x=0) is None
    assert await provider.aversion(z="{z}", y=0, x=0) is None


@pytest.mark.asyncio
async def test_a_bucket_archive_has_the_etag_the_range_cache_knows(tmp_path):
    from app.provider.storage import CachedRanges

    clock = Clock()
    origin = CountingStore(memory_store())
    origin.put(KEY, _archive(tmp_path / "v1.pmtiles").read_bytes())
    provider = _provider(_definition(DATA))
    provider.cached_ranges = CachedRanges(
        origin, KEY, range_cache(memory_store(), clock=clock), source=DATA
    )

    first = await provider.aversion(z=0, y=0, x=0)
    again = await provider.aversion(z=0, y=0, x=0)
    origin.put(KEY, _archive(tmp_path / "v2.pmtiles", label=b"new").read_bytes())
    clock.now += 301
    stale = await provider.aversion(z=0, y=0, x=0)
    await _settled(provider.cached_ranges)
    fresh = await provider.aversion(z=0, y=0, x=0)

    assert first is not None
    assert first == again == stale
    assert origin.heads == 2
    assert fresh != first


@pytest.mark.asyncio
async def test_a_bucket_archive_read_without_the_range_cache_has_no_version():
    provider = _provider(_definition(DATA, range_cache=False))

    assert await provider.aversion(z=0, y=0, x=0) is None
