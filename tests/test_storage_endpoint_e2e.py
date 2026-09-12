"""A dataset is read where it lives, even when the process banks elsewhere (MiniStack).

obstore reads the standard variables in every constructor and, for the
endpoint, lets them win over an explicit ``endpoint`` in the store
options: the store reports the explicit one but sends its requests to
the environment's. This is the case that bit the demo, whose
``AWS_ENDPOINT_URL_S3`` names its own S3-compatible service while a
public dataset lives on AWS.
"""

import os

import pytest

from app.provider.storage import load_store

boto3 = pytest.importorskip("boto3")

BUCKET = "fastgeoapi-elsewhere"
KEY = "probe/hello.txt"
BODY = b"hello from elsewhere"
# The discard port: nobody listens, a connection here is refused at once.
NOBODY_LISTENS = "http://127.0.0.1:9"


@pytest.fixture(scope="module")
def bucket(s3_endpoint) -> str:
    """One object on the local S3, the place the dataset actually lives."""
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    client.put_object(Bucket=BUCKET, Key=KEY, Body=BODY)
    return s3_endpoint


def _options(endpoint: str | None) -> dict:
    options = {
        "region": "us-east-1",
        "key_id": "test",
        "secret": "test",
        "url_style": "path",
        "use_ssl": False,
    }
    if endpoint is not None:
        options["endpoint"] = endpoint.removeprefix("http://")
    return options


def test_an_explicit_endpoint_wins_over_the_environment(bucket, monkeypatch):
    monkeypatch.setenv("AWS_ALLOW_HTTP", "true")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", NOBODY_LISTENS)
    store = load_store(f"s3://{BUCKET}/", _options(bucket))
    assert store.get(KEY) == BODY
    # The environment is only hidden while the store is built, never changed.
    assert os.environ["AWS_ENDPOINT_URL_S3"] == NOBODY_LISTENS


def test_without_an_explicit_endpoint_the_environment_still_applies(bucket, monkeypatch):
    monkeypatch.setenv("AWS_ALLOW_HTTP", "true")
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", bucket)
    store = load_store(f"s3://{BUCKET}/", _options(None))
    assert store.get(KEY) == BODY
