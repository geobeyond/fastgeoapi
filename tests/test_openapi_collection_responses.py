"""The 200 responses of /conformance and /collections name their own schemas.

pygeoapi 0.24 references ``responses/LandingPage`` of OGC API - Features
Part 1 for the landing page, the conformance declaration and the list of
collections (``pygeoapi/openapi.py:298,347,365``). The landing page
schema requires ``links``, which a conformance declaration does not
carry, so a client that validates a response against the document
rejects a correct answer. The same Part 1 document defines
``ConformanceDeclaration`` and ``Collections``.
"""

from pathlib import Path

import pytest
from pygeoapi.util import yaml_load

from app.pygeoapi.factory import build_openapi


@pytest.fixture(scope="module")
def document() -> dict:
    return build_openapi(yaml_load(Path("tests/data/pygeoapi-config.yml").open()))


def _ok(document: dict, path: str) -> str:
    return document["paths"][path]["get"]["responses"]["200"]["$ref"]


def test_conformance_points_at_the_conformance_declaration(document):
    assert _ok(document, "/conformance").endswith("#/components/responses/ConformanceDeclaration")


def test_collections_points_at_the_collections_response(document):
    assert _ok(document, "/collections").endswith("#/components/responses/Collections")


def test_the_landing_page_keeps_its_own_response(document):
    assert _ok(document, "/").endswith("#/components/responses/LandingPage")


def test_the_references_stay_in_the_features_part_1_document(document):
    """Only the fragment changes; the references still point into Features Part 1."""
    landing = _ok(document, "/").split("#")[0]
    assert _ok(document, "/conformance").split("#")[0] == landing
    assert _ok(document, "/collections").split("#")[0] == landing
