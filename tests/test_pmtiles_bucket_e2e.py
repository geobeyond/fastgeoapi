"""A PMTiles archive on S3 (MiniStack): ranged reads through the storage layer, as in production.

The emulator answers honestly about signing, addressing style and HTTP,
which is what this checks; latency and range coalescing stay measured
on a real deployment (ADR-0011, the measurement).
"""

import pytest

from app.provider.pmtiles import PMTilesProvider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive

boto3 = pytest.importorskip("boto3")

BUCKET = "fastgeoapi-tiles"
KEY = "tiles/places.pmtiles"


@pytest.fixture(scope="module")
def bucket(s3_endpoint, tmp_path_factory):
    """A small archive, uploaded to a bucket on the local S3."""
    path = write_archive(
        tmp_path_factory.mktemp("pmtiles") / "places.pmtiles",
        {(1, 0, 1): TILE_BYTES(1, 0, 1)},
    )
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    client.upload_file(str(path), BUCKET, KEY)
    return s3_endpoint


def test_a_tile_is_read_by_range_from_the_bucket(bucket, monkeypatch):
    # obstore refuses plain HTTP unless told so through the environment:
    # `allow_http` in the configuration panics (see storage/factory.py).
    monkeypatch.setenv("AWS_ALLOW_HTTP", "true")
    provider = PMTilesProvider(
        {
            "type": "tile",
            "name": "app.provider.pmtiles.PMTilesProvider",
            "data": f"s3://{BUCKET}/{KEY}",
            "store_options": {
                "endpoint": bucket.removeprefix("http://"),
                "region": "us-east-1",
                "key_id": "test",
                "secret": "test",
                "url_style": "path",
                "use_ssl": False,
            },
            "options": {"zoom": {"min": 0, "max": 2}, "schemes": ["WebMercatorQuad"]},
            "format": {"name": "pbf", "mimetype": "application/vnd.mapbox-vector-tile"},
        }
    )
    assert provider.get_tiles(z=1, y=1, x=0, format_="pbf") == b"tile 1/0/1"
    assert provider.get_tiles(z=1, y=0, x=0, format_="pbf") is None
