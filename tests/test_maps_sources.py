"""Where the renderer reads a collection's data: the object URL and the PMTiles source."""

from datetime import timedelta

from app.maps.contract import MapSource
from app.maps.sources import ObjectUrl, PMTilesSource
from tests.pmtiles_fixtures import TILE_BYTES, write_archive


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_a_local_object_is_a_file_url(tmp_path):
    archive = tmp_path / "roads.pmtiles"

    assert ObjectUrl(local_path=archive).current() == f"file://{archive.resolve()}"


def test_a_public_object_keeps_its_url():
    url = "https://example.org/tiles/roads.pmtiles"

    assert ObjectUrl(public_url=url).current() == url


def test_a_signature_is_renewed_when_a_fifth_of_it_is_left():
    clock, calls = _Clock(), []

    def signer(ttl):
        calls.append(ttl)
        return f"https://bucket.example/roads.pmtiles?sig={len(calls)}"

    url = ObjectUrl(signer=signer, ttl=timedelta(seconds=100), clock=clock)

    first = url.current()
    clock.now = 79
    assert url.current() == first
    clock.now = 80
    assert url.current() != first
    assert calls == [timedelta(seconds=100), timedelta(seconds=100)]


def test_a_pmtiles_source_reads_its_layers_from_the_archive_once(tmp_path):
    archive = write_archive(
        tmp_path / "roads.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "roads", "vector_layers": [{"id": "roads"}, {"id": "water"}]},
    )
    data, reads = archive.read_bytes(), []

    def read(offset, length):
        reads.append((offset, length))
        return data[offset : offset + length]

    source = PMTilesSource(ObjectUrl(local_path=archive), read)

    assert isinstance(source, MapSource)
    assert source.format == "pmtiles"
    assert source.url() == f"file://{archive.resolve()}"
    assert source.layers() == ["roads", "water"]
    first = len(reads)
    assert source.layers() == ["roads", "water"]
    assert len(reads) == first  # the metadata is read once
