"""The PMTiles core never does I/O and never repeats a read (ADR-0011, decisions 2 and 3)."""

import gzip

import pytest
from pmtiles.tile import Compression, zxy_to_tileid
from pygeoapi.provider.base import ProviderQueryError

from app.provider.pmtiles import (
    HEADER_LENGTH,
    LeafCache,
    inflate,
    locate,
    open_archive,
    read_tile,
    zoom_limits,
)
from app.provider.sansio import drive, drive_sync
from tests.pmtiles_fixtures import TILE_BYTES, leafy_archive, write_archive


class _Memory:
    """ByteRanges over bytes, recording every request."""

    def __init__(self, blob: bytes):
        self.blob = blob
        self.reads: list[tuple[int, int]] = []

    def read(self, offset, length):
        self.reads.append((offset, length))
        return self.blob[offset : offset + length]

    async def aread(self, offset, length):
        return self.read(offset, length)

    def read_many(self, ranges):
        return [self.read(offset, length) for offset, length in ranges]

    async def aread_many(self, ranges):
        return self.read_many(ranges)


@pytest.fixture
def small(tmp_path) -> _Memory:
    path = write_archive(
        tmp_path / "small.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0), (2, 1, 3): TILE_BYTES(2, 1, 3)},
    )
    return _Memory(path.read_bytes())


@pytest.fixture(scope="module")
def leafy(tmp_path_factory) -> bytes:
    return leafy_archive(tmp_path_factory.mktemp("pmtiles") / "leafy.pmtiles").read_bytes()


def test_opening_costs_three_reads_and_the_first_is_the_header(small):
    archive = drive_sync(open_archive(LeafCache()), small)
    assert small.reads[0] == (0, HEADER_LENGTH)
    assert len(small.reads) == 3
    assert archive.metadata["name"] == "small"
    assert zoom_limits(archive) == (0, 2)


def test_a_present_tile_is_one_read_once_the_root_is_known(small):
    archive = drive_sync(open_archive(LeafCache()), small)
    small.reads.clear()
    entry = drive_sync(locate(archive, zxy_to_tileid(2, 1, 3)), small)
    raw = drive_sync(read_tile(archive, entry), small)
    assert gzip.decompress(raw) == b"tile 2/1/3"
    assert len(small.reads) == 1


def test_a_missing_tile_costs_no_read_at_all_in_a_root_only_archive(small):
    archive = drive_sync(open_archive(LeafCache()), small)
    small.reads.clear()
    assert drive_sync(locate(archive, zxy_to_tileid(2, 0, 0)), small) is None
    assert small.reads == []


def test_leaf_directories_are_read_once_and_reused(leafy):
    memory = _Memory(leafy)
    archive = drive_sync(open_archive(LeafCache()), memory)
    assert archive.header["leaf_directory_length"] > 0
    memory.reads.clear()
    first = drive_sync(locate(archive, zxy_to_tileid(8, 1, 1)), memory)
    assert first is not None
    assert len(memory.reads) == 1  # the leaf
    memory.reads.clear()
    again = drive_sync(
        locate(archive, zxy_to_tileid(8, 2, 1)), memory
    )  # a neighbour in the same leaf
    assert again is not None
    assert memory.reads == []


@pytest.mark.asyncio
async def test_the_async_driver_gives_the_same_answer(small):
    archive = await drive(open_archive(LeafCache()), small)
    entry = await drive(locate(archive, zxy_to_tileid(2, 1, 3)), small)
    assert gzip.decompress(await drive(read_tile(archive, entry), small)) == b"tile 2/1/3"


def test_inflate_knows_gzip_and_nothing_else():
    assert inflate(gzip.compress(b"x"), Compression.GZIP) == b"x"
    assert inflate(b"x", Compression.NONE) == b"x"
    with pytest.raises(ProviderQueryError, match="BROTLI"):
        inflate(b"x", Compression.BROTLI)


def test_the_leaf_cache_is_bounded():
    cache = LeafCache(maxsize=2)
    cache.put(1, [])
    cache.put(2, [])
    cache.put(3, [])
    assert cache.get(1) is None
    assert cache.get(3) == []
