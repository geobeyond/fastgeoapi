"""Where the renderer reads a collection's data: the object URL, the sources and their registry."""

# The subprocess runs this interpreter with a fixed -c string: nothing
# from outside reaches its arguments.
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from datetime import timedelta
from unittest import mock

import pytest

from app.maps.contract import MapSource, SourceContent
from app.maps.sources import ObjectUrl, PMTilesSource
from tests.pmtiles_fixtures import TILE_BYTES, raster_archive, write_archive


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
    assert source.content() == SourceContent("vector", layers=("roads", "water"), encoding="mvt")
    first = len(reads)
    assert source.content().layers == ("roads", "water")
    assert len(reads) == first  # the metadata is read once


@pytest.mark.parametrize(("size", "gzipped"), [(256, False), (512, True)])
def test_a_raster_archive_is_raster_with_the_size_of_its_tiles(tmp_path, size, gzipped):
    archive = raster_archive(tmp_path / "hills.pmtiles", size=size, gzipped=gzipped)
    data = archive.read_bytes()

    source = PMTilesSource(ObjectUrl(local_path=archive), lambda o, n: data[o : o + n])

    assert source.content() == SourceContent("raster", tile_size=size, encoding="png")


def test_the_tile_size_option_spares_the_read_of_a_tile(tmp_path):
    archive = raster_archive(tmp_path / "hills.pmtiles", size=256)
    data, reads = archive.read_bytes(), []

    def read(offset, length):
        reads.append((offset, length))
        return data[offset : offset + length]

    source = PMTilesSource(ObjectUrl(local_path=archive), read, tile_size=512)

    assert source.content() == SourceContent("raster", tile_size=512, encoding="png")
    assert reads == [(0, 127)]  # the header alone


@pytest.mark.parametrize(
    "data", ["roads.pmtiles", "s3://bucket/tiles/Roads.PMTiles", "https://host/a.pmtiles?x=1"]
)
def test_a_pmtiles_archive_finds_its_source(data):
    from app.maps.sources import source_for

    assert source_for(data).format == "pmtiles"


def test_data_that_no_source_reads_is_refused():
    from app.maps.sources import source_for

    with pytest.raises(LookupError, match=r"roads\.parquet"):
        source_for("s3://bucket/roads.parquet")


def test_a_registered_source_is_found_by_its_data():
    from app.maps import sources

    with mock.patch.dict(sources._REGISTRY):
        sources.register_source(
            "geojson", matches=lambda data: data.endswith(".geojson"), build=lambda context: None
        )
        assert sources.source_for("roads.geojson").format == "geojson"
    with pytest.raises(LookupError):
        sources.source_for("roads.geojson")


def test_the_map_provider_imports_without_the_pmtiles_extra():
    """Only a PMTiles source needs the pmtiles package, and only when it reads the archive."""
    code = (
        "import sys;"
        "sys.modules['pmtiles'] = None;"
        "sys.modules['pmtiles.reader'] = None;"
        "import app.provider.maplibre"
    )
    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr[-800:]
