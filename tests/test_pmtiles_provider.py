"""The PMTiles provider on a local archive: both faces, pygeoapi's semantics, metadata from the archive.

Imports stay at module level and spies are installed with
``monkeypatch.setattr`` on the module object (other test modules purge
``app.*`` from ``sys.modules``).
"""

import asyncio
import gzip
import os
import threading

import pytest
from pygeoapi.provider.tile import ProviderTileNotFoundError

import app.provider.pmtiles as pmtiles_module
from app.interfaces import AsyncTileProvider
from app.provider.base import async_view
from app.provider.pmtiles import PMTilesProvider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive

# Incompressible on purpose: gzip must leave it above the inline-inflate limit.
BIG = os.urandom(300 * 1024)
SERVER = "http://localhost:5000/geoapi"
SERVICE_PATH = f"{SERVER}/collections/places/tiles/{{tileMatrixSetId}}/{{tileMatrix}}/{{tileRow}}/{{tileCol}}?f=pbf"


def _definition(path, zoom=(0, 2)) -> dict:
    return {
        "type": "tile",
        "name": "app.provider.pmtiles.PMTilesProvider",
        "data": str(path),
        "options": {"zoom": {"min": zoom[0], "max": zoom[1]}, "schemes": ["WebMercatorQuad"]},
        "format": {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"},
    }


@pytest.fixture
def archive(tmp_path):
    return write_archive(
        tmp_path / "places.pmtiles",
        {
            (0, 0, 0): TILE_BYTES(0, 0, 0),
            (2, 1, 3): TILE_BYTES(2, 1, 3),
            (2, 3, 3): gzip.compress(BIG),
        },
        metadata={
            "name": "Places",
            "attribution": "© Test",
            "vector_layers": [{"id": "place", "minzoom": 0, "maxzoom": 2}],
        },
    )


@pytest.fixture
def provider(archive) -> PMTilesProvider:
    return PMTilesProvider(_definition(archive))


def test_the_provider_is_native_and_conforms(provider):
    assert provider.native_async is True
    assert provider.THREAD_SAFE is True
    assert isinstance(provider, AsyncTileProvider)


def test_construction_reads_nothing(archive, monkeypatch):
    reads = []

    def forbidden(*args, **kwargs):
        reads.append(args)
        raise AssertionError("no I/O while constructing")

    monkeypatch.setattr(pmtiles_module, "drive_sync", forbidden)
    PMTilesProvider(_definition(archive))
    assert reads == []


def test_both_faces_return_the_decompressed_tile(provider):
    sync = provider.get_tiles(
        layer="places", tileset="WebMercatorQuad", z=2, y=3, x=1, format_="pbf"
    )
    assert sync == b"tile 2/1/3"
    assert asyncio.run(provider.aget_tiles("places", "WebMercatorQuad", 2, 3, 1, "pbf")) == sync


def test_a_missing_tile_within_limits_is_none(provider):
    assert provider.get_tiles(z=2, y=0, x=0, format_="pbf") is None


def test_a_tile_outside_the_archive_zoom_is_not_found(archive):
    provider = PMTilesProvider(
        _definition(archive, zoom=(0, 5))
    )  # config says 5, the archive says 2
    with pytest.raises(ProviderTileNotFoundError):
        provider.get_tiles(z=4, y=0, x=0, format_="pbf")


def test_a_tile_outside_the_configured_zoom_is_not_found(provider):
    with pytest.raises(ProviderTileNotFoundError):
        provider.get_tiles(z=7, y=0, x=0, format_="pbf")


@pytest.mark.asyncio
async def test_big_tiles_are_inflated_off_the_loop(provider, monkeypatch):
    # `inflate` also runs once for the metadata when the archive opens, so
    # the records are keyed by size rather than by call order.
    records: list[tuple[int, str]] = []
    original = pmtiles_module.inflate

    def spy(data, compression):
        records.append((len(data), threading.current_thread().name))
        return original(data, compression)

    monkeypatch.setattr(pmtiles_module, "inflate", spy)
    small = await provider.aget_tiles("places", "WebMercatorQuad", 2, 3, 1, "pbf")
    big = await provider.aget_tiles("places", "WebMercatorQuad", 2, 3, 3, "pbf")
    assert small == b"tile 2/1/3"
    assert big == BIG
    loop_thread = threading.current_thread().name
    small_threads = {thread for size, thread in records if size <= provider.inline_inflate_limit}
    big_threads = {thread for size, thread in records if size > provider.inline_inflate_limit}
    assert small_threads == {loop_thread}  # inline
    assert big_threads and loop_thread not in big_threads  # a worker


def test_metadata_comes_from_the_archive(provider):
    tilejson = provider.get_vendor_metadata(
        dataset="places",
        server_url=SERVER,
        layer="places",
        tileset="WebMercatorQuad",
        title="Places",
        description="d",
        keywords=[],
    )
    assert tilejson["name"] == "Places"
    assert tilejson["attribution"] == "© Test"
    assert (tilejson["minzoom"], tilejson["maxzoom"]) == (0, 2)
    assert tilejson["vector_layers"][0]["id"] == "place"
    # pygeoapi's TileJSON model carries bounds, center and tiles as strings.
    assert tilejson["bounds"] == "-180.0,-85.0511287,180.0,85.0511287"
    assert "{tileMatrix}/{tileRow}/{tileCol}" in tilejson["tiles"]


def test_tiling_scheme_and_service_links(provider):
    assert [scheme.tileMatrixSet for scheme in provider.get_tiling_schemes()] == ["WebMercatorQuad"]
    links = provider.get_tiles_service(baseurl=SERVER, servicepath=SERVICE_PATH)
    assert {link["rel"] for link in links["links"]} == {"self", "item", "describedby"}
    assert provider.get_layer() == "places"


def test_default_metadata_names_the_tiling_scheme(provider):
    metadata = provider.get_default_metadata(
        dataset="places",
        server_url=SERVER,
        layer="places",
        tileset="WebMercatorQuad",
        title="Places",
        description="d",
        keywords=["k"],
    )
    assert metadata["tileMatrixSetURI"].endswith("WebMercatorQuad")
    assert {link["rel"] for link in metadata["links"]} == {
        "http://www.opengis.net/def/rel/ogc/1.0/tiling-scheme",
        "item",
    }


@pytest.mark.asyncio
async def test_async_view_uses_the_native_face(provider):
    assert await async_view(provider).get_tiles(z=0, y=0, x=0, format_="pbf") == b"tile 0/0/0"


def test_non_numeric_tile_coordinates_are_not_found_not_a_crash(provider):
    """A template pasted literally (`{tileMatrix}`) is a 404 in pygeoapi's chain; ours must agree."""
    with pytest.raises(ProviderTileNotFoundError):
        provider.get_tiles(z="{tileMatrix}", y="{tileRow}", x="{tileCol}", format_="pbf")
