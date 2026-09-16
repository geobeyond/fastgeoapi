"""The document and the declaration agree, checked on every change.

There is already a lane that validates conformance, but it runs on
`workflow_run` after a deployment and interrogates the live server, so
it reports nowhere a commit can see: it was failing for forty days
without appearing as a check on a single pull request.

This is the other half. An instance with the same shapes as the demo —
a feature collection, a tile collection, a process with a job manager —
is built in process, and its own OpenAPI document and conformance
declaration are handed to the same validator. No network, no port, under
two seconds, and it fails the pull request that introduces a divergence
rather than a deployment three merges later.

The deployed lane keeps its own job: this one says the repository is
coherent, that one says production still matches it.
"""

from __future__ import annotations

import pytest

from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_pmtiles_route import _provider
from tests.test_tiles_async_route import _collection, _config


@pytest.fixture(scope="module")
def served(tmp_path_factory) -> tuple[dict, dict]:
    """The document a client reads, and the classes the server claims."""
    from starlette.testclient import TestClient

    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    workdir = tmp_path_factory.mktemp("conformance")
    archive = write_archive(
        workdir / "places.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={
            "name": "Places",
            "vector_layers": [{"id": "place", "minzoom": 0, "maxzoom": 2}],
        },
    )

    config = _config({"places": _collection("Places", [_provider(archive)])})
    config["resources"]["hello-world"] = {
        "type": "process",
        "processor": {"name": "HelloWorld"},
    }
    # Without a manager reporting `is_async`, pygeoapi leaves the job
    # endpoints out of the document while serving them — the same reason
    # the demo's configuration names one.
    config["server"]["manager"] = {
        "name": "TinyDB",
        "connection": str(workdir / "jobs.db"),
        "output_dir": str(workdir),
    }

    document = build_openapi(config)
    client = TestClient(build_pygeoapi_subapp(config, document))
    declaration = client.get("/conformance", params={"f": "json"}).json()
    return document, declaration


def test_nothing_is_declared_that_the_document_does_not_describe(served):
    """The whole point, in one assertion.

    A critical finding here means the server claims a conformance class
    whose resources its own OpenAPI does not describe — which is what
    sent three different clients down three wrong paths this week.
    """
    from ogcapi_registry import parse_conformance_classes, validate_ogc_api

    document, declaration = served

    result = validate_ogc_api(document, parse_conformance_classes(declaration))
    findings = [
        finding.get("message")
        for finding in (getattr(result, "errors", None) or [])
        if finding.get("severity") == "critical"
    ]

    assert findings == []


def test_the_tileset_path_is_what_this_would_have_caught(served):
    """A named guard for the divergence that was open until today.

    pygeoapi serves `/collections/{id}/tiles/{tileMatrixSetId}` and never
    writes it into the document; `describe_tilesets` adds it. Losing that
    patch turns the assertion above red, and this says why.
    """
    document, _ = served

    assert "/collections/places/tiles/{tileMatrixSetId}" in document["paths"]
