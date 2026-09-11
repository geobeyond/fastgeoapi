"""A provider's data object as byte ranges, through the storage layer (ADR-0010, decision 7).

Imports stay at module level and the spy is installed with
``monkeypatch.setattr`` on the module object: other test modules purge
``app.*`` from ``sys.modules``, and a patch by dotted string would land
on a re-imported module the code under test never sees.
"""

from pathlib import Path

import pytest

import app.provider.base as provider_base
from app.provider.base import AsyncProviderMixin, StorageBackedMixin
from app.provider.storage import ByteRanges, load_store

BLOB = bytes(range(256))


class _Root:
    """pygeoapi-like: keeps `data`, never calls super()."""

    def __init__(self, provider_def):
        self.data = provider_def["data"]


class _Backed(AsyncProviderMixin, StorageBackedMixin, _Root):
    pass


class _Wrong(_Root, AsyncProviderMixin, StorageBackedMixin):
    """The mixin after the root: provider_def is never captured."""


@pytest.fixture
def blob(tmp_path) -> str:
    path = tmp_path / "blob.bin"
    path.write_bytes(BLOB)
    return str(path)


def test_byte_ranges_read_the_provider_data_object(blob):
    ranges = _Backed({"name": "x", "data": blob}).byte_ranges()
    assert isinstance(ranges, ByteRanges)
    assert ranges.read(10, 5) == BLOB[10:15]
    assert ranges.read_many([(0, 2), (254, 2)]) == [BLOB[0:2], BLOB[254:256]]


@pytest.mark.asyncio
async def test_the_async_side_reads_the_same_bytes(blob):
    ranges = _Backed({"name": "x", "data": blob}).byte_ranges()
    assert await ranges.aread(10, 5) == BLOB[10:15]
    assert await ranges.aread_many([(0, 2), (254, 2)]) == [BLOB[0:2], BLOB[254:256]]


def test_store_options_travel_from_provider_def(blob, monkeypatch):
    seen = {}

    def spy(base, store_options=None):
        seen["args"] = (base, store_options)
        return load_store(base)

    monkeypatch.setattr(provider_base, "load_store", spy)
    provider = _Backed({"name": "x", "data": blob, "store_options": {"region": "eu"}})
    provider.store  # ruff: ignore[useless-expression]
    assert seen["args"] == (str(Path(blob).parent), {"region": "eu"})


def test_the_store_is_built_once(blob):
    provider = _Backed({"name": "x", "data": blob})
    assert provider.store is provider.store


def test_the_wrong_base_order_fails_naming_the_fix(blob):
    with pytest.raises(TypeError, match="AsyncProviderMixin first"):
        _Wrong({"name": "x", "data": blob}).byte_ranges()
