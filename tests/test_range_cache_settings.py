"""Where the range cache lives, and which providers read through it."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.range_cache_fixtures import memory_store, range_cache


def _settings(**values):
    defaults = {
        "FASTGEOAPI_CACHE_DIR": None,
        "FASTGEOAPI_RANGE_CACHE": None,
        "FASTGEOAPI_RANGE_CACHE_MAX_MB": 512,
        "FASTGEOAPI_RANGE_CACHE_REVALIDATE_SECONDS": 300,
    }
    return SimpleNamespace(**{**defaults, **values})


def _provider(data, **options):
    from app.provider.base import AsyncProviderMixin, StorageBackedMixin

    class _Root:
        def __init__(self, provider_def):
            self.data = provider_def["data"]

    class _Backed(AsyncProviderMixin, StorageBackedMixin, _Root):
        pass

    return _Backed({"name": "x", "data": data, "options": options})


def test_unset_the_cache_lives_next_to_the_schema_cache(tmp_path):
    from app.provider.storage.cache import range_cache_from

    cache = range_cache_from(_settings(FASTGEOAPI_CACHE_DIR=str(tmp_path)))
    cache.put("s/v/0-1", b"x")

    assert (tmp_path / "ranges" / "s" / "v" / "0-1").read_bytes() == b"x"
    assert (cache.max_bytes, cache.revalidate_seconds) == (512 * 1024 * 1024, 300.0)


@pytest.mark.parametrize("value", ["off", "OFF", " Off "])
def test_off_turns_the_cache_off(value):
    from app.provider.storage.cache import range_cache_from

    assert range_cache_from(_settings(FASTGEOAPI_RANGE_CACHE=value)) is None


def test_a_directory_and_the_limits_come_from_the_settings(tmp_path):
    from app.provider.storage.cache import range_cache_from

    cache = range_cache_from(
        _settings(
            FASTGEOAPI_RANGE_CACHE=str(tmp_path / "r"),
            FASTGEOAPI_RANGE_CACHE_MAX_MB=2,
            FASTGEOAPI_RANGE_CACHE_REVALIDATE_SECONDS=5,
        )
    )
    cache.put("s/v/0-1", b"x")

    assert (tmp_path / "r" / "s" / "v" / "0-1").exists()
    assert (cache.max_bytes, cache.revalidate_seconds) == (2 * 1024 * 1024, 5.0)


def test_the_suite_runs_with_the_cache_off():
    from app.provider.storage import cache as range_caches

    range_caches.default_range_cache.cache_clear()
    assert range_caches.default_range_cache() is None
    assert range_caches.range_cache_enabled() is False


def test_local_data_is_never_read_through_the_cache(tmp_path):
    assert _provider(str(tmp_path / "a.pmtiles")).cached_ranges is None


def test_range_cache_false_keeps_a_bucket_out_of_the_cache():
    from app.provider.storage import cache as range_caches

    with patch.object(
        range_caches, "default_range_cache", return_value=range_cache(memory_store())
    ):
        assert _provider("s3://bucket/a.pmtiles", range_cache=False).cached_ranges is None


def test_a_bucket_reads_through_the_process_cache():
    from app.provider.storage import CachedRanges
    from app.provider.storage import cache as range_caches

    cache = range_cache(memory_store())
    with patch.object(range_caches, "default_range_cache", return_value=cache):
        cached = _provider("s3://bucket/tiles/a.pmtiles").cached_ranges

    assert isinstance(cached, CachedRanges)
    assert (cached.key, cached.cache) == ("a.pmtiles", cache)
