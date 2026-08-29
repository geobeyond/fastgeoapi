"""The editor against a configuration that lives in a bucket.

This is the case the editor exists for. A local file can be opened in
any text editor; what cannot is the document a deployment reads from
object storage and applies without a restart (ADR-0003). Everything else
in the editor suite works on `tmp_path`, which shares the code path but
never signs a request or sends one.

What only shows up here is the write. Refusing an invalid document
*before* writing is the rule the whole surface exists to respect, and
locally a bad write is a bad file — recoverable, visible, yours.
Remotely it is a new object version in a store a running deployment is
one webhook call away from reading. The invariant is the same; the
consequence of breaking it is not.
"""

import pytest
from starlette.testclient import TestClient

from app.editor.app import EDITOR_TOKEN_HEADER, build_authoring_app

BUCKET = "fastgeoapi-editor-test"
KEY = "config/pygeoapi-config.yml"

DOCUMENT = """\
server:
    bind:
        host: ${HOST}
        port: ${PORT}
    url: http://localhost:5000
    mimetype: application/json; charset=UTF-8
    encoding: utf-8
    language: en-US
    map:
        url: https://tile.openstreetmap.org/{z}/{x}/{y}.png
        attribution: OpenStreetMap contributors
logging:
    level: ERROR
metadata:
    identification:
        title: In a bucket
        description: A configuration that does not live on a filesystem
        keywords: [geospatial, data, api]
        keywords_type: theme
        terms_of_service: https://creativecommons.org/licenses/by/4.0/
        url: https://example.org
    license:
        name: CC-BY 4.0 license
        url: https://creativecommons.org/licenses/by/4.0/
    provider:
        name: Organization Name
        url: https://example.org
    contact:
        name: Lastname, Firstname
        position: Position Title
        address: Mailing Address
        city: City
        stateorprovince: Administrative Area
        postalcode: Zip or Postal Code
        country: Country
        email: you@example.org
        url: https://example.org
        hours: Mo-Fr 08:00-17:00
        instructions: During hours of service.
        role: pointOfContact
resources: {}
"""


@pytest.fixture(scope="module")
def bucket_config(s3_endpoint):
    """The document, uploaded to a bucket on the local S3."""
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    client.put_object(Bucket=BUCKET, Key=KEY, Body=DOCUMENT.encode())
    return client


@pytest.fixture
def editor(s3_endpoint, bucket_config, monkeypatch):
    """An editor pointed at the bucket, reached the way a deployment is.

    Credentials come from the environment and nowhere else: `load_store`
    takes them from each cloud's standard variables, which is what makes
    the same document readable here and on the deployment.
    """
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", s3_endpoint)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ALLOW_HTTP", "true")

    app = build_authoring_app(host="127.0.0.1", source=f"s3://{BUCKET}/{KEY}")
    client = TestClient(app)
    client.headers[EDITOR_TOKEN_HEADER] = app.state.editor_token
    return client


def _in_bucket(client) -> str:
    return client.get_object(Bucket=BUCKET, Key=KEY)["Body"].read().decode()


def test_the_document_is_read_from_the_bucket(editor):
    """Placeholders intact: the source, not the effective form."""
    body = editor.get("/editor/config").json()

    assert "In a bucket" in body["document"], body["document"][:200]
    assert "${PORT}" in body["document"], body["document"][:200]


def test_a_save_lands_in_the_bucket(editor, bucket_config):
    """The round trip that a local path cannot prove: read, edit, PUT."""
    changed = DOCUMENT.replace("title: In a bucket", "title: Renamed in a bucket", 1)

    response = editor.put("/editor/config", json={"document": changed})

    assert response.status_code == 200, response.text
    assert "Renamed in a bucket" in _in_bucket(bucket_config)


def test_a_refused_document_never_reaches_the_bucket(editor, bucket_config):
    """The invariant that matters most, where breaking it costs the most.

    A refusal that followed the write would leave object storage holding
    a configuration that cannot start — and unlike a local file, that one
    is already visible to a deployment that reloads on demand.

    The bucket is confirmed reachable *through the editor* first. Without
    that, this test would pass just as happily against an editor that
    could not write at all — proving nothing about the refusal.
    """
    before = _in_bucket(bucket_config)
    assert editor.get("/editor/config").status_code == 200, "the store is not reachable"

    response = editor.put("/editor/config", json={"document": "resources: [oops]"})

    assert response.status_code == 422, response.text
    assert _in_bucket(bucket_config) == before, "the object in the bucket was modified"
