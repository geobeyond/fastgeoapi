"""Presigned URLs for an object, from the store that holds it."""

from datetime import timedelta

import pytest
from obstore.store import S3Store

from app.provider.storage import ObstoreStore


def _s3() -> ObstoreStore:
    return ObstoreStore(
        S3Store(
            "bucket",
            endpoint="https://example.invalid",
            region="us-east-1",
            access_key_id="AKIDEXAMPLE",
            secret_access_key="secret",
        )
    )


def test_an_s3_store_signs_a_get_for_the_object():
    url = _s3().sign("tiles/a.pmtiles", timedelta(minutes=5))

    assert url.startswith("https://")
    assert "tiles/a.pmtiles" in url
    assert "X-Amz-Signature" in url


def test_a_provider_signs_its_own_data_object():
    from app.provider.base import AsyncProviderMixin, StorageBackedMixin

    class _Root:
        def __init__(self, provider_def):
            pass

    class _Provider(AsyncProviderMixin, StorageBackedMixin, _Root):
        pass

    provider = _Provider(
        {
            "name": "p",
            "data": "s3://bucket/tiles/a.pmtiles",
            "store_options": {
                "endpoint": "https://example.invalid",
                "region": "us-east-1",
                "access_key_id": "AKIDEXAMPLE",
                "secret_access_key": "secret",
            },
        }
    )

    # The store is scoped to the "tiles/" prefix and the key is "a.pmtiles":
    # the signed URL must still name the whole object.
    assert "/bucket/tiles/a.pmtiles?" in provider.signed_url(timedelta(minutes=5))


def test_a_store_that_cannot_sign_says_so():
    from app.provider.base import AsyncProviderMixin, StorageBackedMixin

    class _Root:
        def __init__(self, provider_def):
            pass

    class _Provider(AsyncProviderMixin, StorageBackedMixin, _Root):
        pass

    provider = _Provider({"name": "p", "data": "/tmp/a.pmtiles"})
    provider.__dict__["store"] = object()

    with pytest.raises(TypeError, match="cannot sign"):
        provider.signed_url(timedelta(minutes=5))
