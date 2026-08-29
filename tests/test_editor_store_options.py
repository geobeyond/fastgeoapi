"""The dry run has to reach a source the way the provider reaches it.

Found on the real thing. Running a dry run against the deployment's own
configuration reported `overture-places` as unreachable while the very
same run listed it among the collections it had served — the check that
asks for one item succeeded, and the check that looks at the source
failed. A report that contradicts itself is worse than no report: an
operator cannot tell which half to believe.

The cause is that a provider carries `store_options` — the region, an
S3-compatible `endpoint`, `skip_signature` for public data — and the
source check was building its store without them. So it signed a public
bucket with whatever credentials the process happened to hold, and sent
the request wherever `AWS_ENDPOINT_URL_S3` happened to point.

That second half is the failure that cost a production afternoon and is
already pinned for the provider (`test_the_dataset_endpoint_beats_the_
environment`). It is reproduced here for the editor, which is a second
consumer of the same storage layer and inherited the same trap.
"""

import pytest

from app.editor.inspect import _unreachable_sources, dry_run

BUCKET = "fastgeoapi-editor-options"
KEY = "lakes/lakes.parquet"


@pytest.fixture(scope="module")
def dataset(s3_endpoint):
    """The fixture dataset, on a bucket the ambient environment cannot see."""
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    client.create_bucket(Bucket=BUCKET)
    client.upload_file("tests/data/lakes.parquet", BUCKET, KEY)
    return s3_endpoint


def _document(endpoint: str) -> str:
    """A configuration whose only dataset needs its own store options."""
    from pathlib import Path

    base = Path("tests/data/pygeoapi-config.yml").read_text()
    head = base[: base.index("resources:")]
    return (
        head
        + f"""resources:
    lakes:
        type: collection
        title: Lakes
        description: Lakes on a store the environment does not know about
        keywords: [lakes]
        extents:
            spatial:
                bbox: [-180, -90, 180, 90]
                crs: http://www.opengis.net/def/crs/OGC/1.3/CRS84
        providers:
            - type: feature
              name: app.provider.geoparquet.GeoParquetProvider
              data: s3://{BUCKET}/{KEY}
              id_field: id
              geometry_column: geometry
              store_options:
                  endpoint: {endpoint.removeprefix("http://")}
                  region: us-east-1
                  key_id: test
                  secret: test
                  url_style: path
                  use_ssl: false
"""
    )


def test_the_source_check_uses_the_provider_store_options(dataset, monkeypatch):
    """The dataset's own settings must beat the process environment.

    Without them the check reaches for ambient credentials and an ambient
    endpoint — here a closed port — and reports a source that is
    perfectly readable as missing.
    """
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "belonging-to-another-store")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "belonging-to-another-store")
    # Not a credential and not an address: obstore 0.11.1 panics when
    # `allow_http` comes through the configuration, so plain HTTP can
    # only be allowed from the environment. A real store speaks TLS.
    monkeypatch.setenv("AWS_ALLOW_HTTP", "true")
    for name, value in (
        ("HOST", "0.0.0.0"),
        ("PORT", "5000"),
        ("PYGEOAPI_BASEURL", "http://localhost:5000"),
        ("FASTGEOAPI_CONTEXT", "/geoapi"),
    ):
        monkeypatch.setenv(name, value)

    outcome = dry_run(_document(dataset))

    assert not any("cannot reach" in problem for problem in outcome.problems), outcome.problems


def test_an_empty_prefix_is_reported_as_empty_not_as_a_crash(dataset, monkeypatch):
    """A prefix with nothing under it has its own answer.

    `stat` fails for a prefix — there is no object by that name — so the
    check falls back to listing. Listing belongs to the store, not to the
    bridge that wraps it, and reaching for it on the wrong object turns
    "nothing is there" into an `AttributeError` shown to the operator as
    if it were a fact about their configuration.
    """
    monkeypatch.setenv("AWS_ALLOW_HTTP", "true")
    config = {
        "resources": {
            "lakes": {
                "providers": [
                    {
                        "data": f"s3://{BUCKET}/no-such-prefix/",
                        "store_options": {
                            "endpoint": dataset.removeprefix("http://"),
                            "region": "us-east-1",
                            "key_id": "test",
                            "secret": "test",
                            "url_style": "path",
                            "use_ssl": False,
                        },
                    }
                ]
            }
        }
    }

    problems = [why for _, _, why in _unreachable_sources(config)]

    assert problems == ["nothing is there"], problems
