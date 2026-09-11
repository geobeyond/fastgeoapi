"""The fixture generator: archives the pmtiles library itself can read back."""

import gzip

from pmtiles.reader import MemorySource, Reader
from pmtiles.tile import deserialize_header

from tests.pmtiles_fixtures import TILE_BYTES, leafy_archive, write_archive


def test_a_small_archive_reads_back(tmp_path):
    path = write_archive(
        tmp_path / "small.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0), (1, 1, 0): TILE_BYTES(1, 1, 0)},
    )
    reader = Reader(MemorySource(path.read_bytes()))
    assert gzip.decompress(reader.get(1, 1, 0)) == b"tile 1/1/0"
    assert reader.get(1, 0, 0) is None
    assert reader.metadata()["vector_layers"][0]["id"] == "layer"


def test_the_leafy_archive_has_leaf_directories(tmp_path):
    path = leafy_archive(tmp_path / "leafy.pmtiles")
    header = deserialize_header(path.read_bytes()[:127])
    assert header["leaf_directory_length"] > 0
    assert header["min_zoom"] == header["max_zoom"] == 8
