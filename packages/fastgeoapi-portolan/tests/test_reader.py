"""The reader the commands use: obstore for the documents, the bundled schemas to check them."""

from __future__ import annotations

from dataclasses import fields

import pytest

from fastgeoapi_portolan.catalog.testing import check_async_transport, write_fixtures
from fastgeoapi_portolan.reader import read_catalog, read_items
from fastgeoapi_portolan.storage import ObstoreTransport

BUCKET = "portolan-kit"


@pytest.mark.asyncio
async def test_the_kit_passes_with_the_obstore_transport(tmp_path):
    await check_async_transport(ObstoreTransport(), tmp_path)


@pytest.mark.asyncio
async def test_the_reader_validates_with_the_bundled_schemas(tmp_path):
    fixtures = write_fixtures(tmp_path)

    catalog = await read_catalog(str(fixtures.nonconforming))

    assert catalog.validated is True
    assert catalog.collections == ()
    (rejected,) = catalog.nonconforming
    assert (rejected.kind, rejected.document["id"]) == ("Collection", "untitled")
    assert any("'title'" in finding.message for finding in rejected.findings)
    assert (await read_catalog(str(fixtures.nested))).nonconforming == ()


@pytest.mark.asyncio
async def test_the_reader_reads_and_checks_the_items(tmp_path):
    fixtures = write_fixtures(tmp_path)
    (buildings,) = (await read_catalog(str(fixtures.partitioned))).collections

    items = await read_items(buildings)

    assert [item["id"] for item in items.items] == ["part-0", "part-1", "part-2"]
    assert items.nonconforming == ()


@pytest.mark.asyncio
async def test_the_walk_stops_at_max_documents(tmp_path):
    fixtures = write_fixtures(tmp_path)

    catalog = await read_catalog(str(fixtures.nested), max_documents=2)

    assert catalog.collections == ()
    assert any("its limit of 2 documents" in warning for warning in catalog.warnings)


@pytest.mark.asyncio
async def test_a_document_over_max_bytes_is_not_read(tmp_path):
    fixtures = write_fixtures(tmp_path)

    with pytest.raises(OSError, match="larger than 100 bytes"):
        await read_catalog(str(fixtures.nested), max_bytes=100)


@pytest.mark.asyncio
async def test_a_collection_with_more_items_than_max_items_is_not_read(tmp_path):
    fixtures = write_fixtures(tmp_path)
    (buildings,) = (await read_catalog(str(fixtures.partitioned))).collections

    with pytest.raises(ValueError, match="more than the 2"):
        await read_items(buildings, max_items=2)


@pytest.mark.asyncio
async def test_an_item_over_max_bytes_is_not_read(tmp_path):
    fixtures = write_fixtures(tmp_path)
    (buildings,) = (await read_catalog(str(fixtures.partitioned))).collections

    with pytest.raises(OSError, match="larger than 100 bytes"):
        await read_items(buildings, max_bytes=100)


@pytest.fixture
def kit_in_a_bucket(s3_endpoint, tmp_path, monkeypatch):
    """The kit on disk, the same files on the local S3, and the options to read them."""
    boto3 = pytest.importorskip("boto3")
    monkeypatch.delenv("AWS_ALLOW_HTTP", raising=False)
    fixtures = write_fixtures(tmp_path)
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    base = tmp_path.resolve()
    for path in base.rglob("*"):
        if path.is_file():
            client.put_object(
                Bucket=BUCKET,
                Key=f"kit/{path.relative_to(base).as_posix()}",
                Body=path.read_bytes(),
            )
    store_options = {
        "endpoint": s3_endpoint.removeprefix("http://"),
        "use_ssl": False,
        "url_style": "path",
        "region": "us-east-1",
        "key_id": "test",
        "secret": "test",
    }
    return fixtures, base, store_options


def _seen(catalog, folder):
    """What a walk found, with every href relative to the folder of the root."""
    return (
        sorted(collection.id for collection in catalog.collections),
        sorted(entry.href.removeprefix(folder) for entry in catalog.nonconforming),
        sorted((entry.collection.removeprefix(folder), entry.reason) for entry in catalog.skipped),
    )


@pytest.mark.asyncio
async def test_a_catalog_in_a_bucket_reads_like_on_disk(kit_in_a_bucket):
    fixtures, base, store_options = kit_in_a_bucket

    for case in fields(fixtures):
        on_disk = await read_catalog(str(getattr(fixtures, case.name)))
        in_bucket = await read_catalog(f"s3://{BUCKET}/kit/{case.name}/catalog.json", store_options)

        assert _seen(in_bucket, f"s3://{BUCKET}/kit/{case.name}/") == _seen(
            on_disk, f"{base / case.name}/"
        ), case.name
