"""Every requirement of a declared conformance class is checked or waived."""

import ast
from pathlib import Path
from unittest.mock import patch

import pytest
from ogcapi_registry import KNOWN_CONFORMANCE_CLASSES, KNOWN_REQUIREMENTS, list_requirements

from app.pygeoapi import factory
from app.pygeoapi.api.conformance import build_conformance_list
from tests.conformance.conftest import CONFIGURATIONS, Served, load_config
from tests.conformance.requirements import CHECKED, DRAFTS, WAIVED

COLLECTION_MAP = "http://www.opengis.net/spec/ogcapi-maps-1/1.0/conf/collection-map"


def list_declared_classes(config: dict) -> list[str]:
    """List the conformance classes a configuration declares.

    The list comes from the function that answers ``/conformance``, which
    reads the configuration and loads the providers. Building the OpenAPI
    document would read the schemas of the remote data, so a network failure
    would skip the check instead of running it.

    Parameters
    ----------
    config
        The loaded configuration.

    Returns
    -------
    list of str
        The URIs of ``/conformance``, with ``http://`` as the catalogue
        writes them.
    """
    response = build_conformance_list(config["resources"], has_pubsub="pubsub" in config)
    return [uri.replace("https://", "http://", 1) for uri in response.conforms_to]


@pytest.fixture(name="declared", scope="module", params=list(CONFIGURATIONS))
def list_configured_classes(request: pytest.FixtureRequest) -> list[str]:
    """List the conformance classes one configuration declares.

    Parameters
    ----------
    request
        Carries the id of the configuration in ``CONFIGURATIONS``.

    Returns
    -------
    list of str
        The URIs of its ``/conformance``.
    """
    return list_declared_classes(load_config(request.param))


def test_the_declared_classes_need_no_data():
    with patch.object(factory, "build_openapi", side_effect=AssertionError("read the data")):
        declared = list_declared_classes(load_config("demo"))

    assert COLLECTION_MAP in declared


def test_the_declared_classes_are_those_conformance_serves(served: Served):
    response = served.client.get("/conformance", params={"f": "json"})
    served_classes = [
        uri.replace("https://", "http://", 1) for uri in response.json()["conformsTo"]
    ]

    assert list_declared_classes(served.config) == served_classes


def list_test_names(path: Path) -> set[str]:
    """List the test functions a module defines.

    The module is parsed, not imported, so naming a test does not run the
    imports of its module.

    Parameters
    ----------
    path
        The test module.

    Returns
    -------
    set of str
        The names of its functions, at any depth.
    """
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def test_every_declared_requirement_is_checked_or_waived(declared):
    missing = [
        requirement.uri
        for conformance_class in declared
        for requirement in list_requirements(conformance_class)
        if requirement.uri not in CHECKED and requirement.uri not in WAIVED
    ]

    assert missing == []


def test_a_declared_class_outside_the_catalogue_is_a_known_draft(declared):
    unknown = [
        conformance_class
        for conformance_class in declared
        if conformance_class not in KNOWN_CONFORMANCE_CLASSES and conformance_class not in DRAFTS
    ]

    assert unknown == []


def test_every_check_names_a_test_that_exists():
    missing = []
    for uri, node in CHECKED.items():
        module, _, name = node.partition("::")
        path = Path(module)
        if not path.is_file() or name.split("[")[0] not in list_test_names(path):
            missing.append(f"{uri}: {node}")

    assert missing == []


def test_no_waiver_is_stale():
    checked_and_waived = sorted(CHECKED.keys() & WAIVED.keys())
    uncatalogued = sorted((CHECKED.keys() | WAIVED.keys()) - KNOWN_REQUIREMENTS.keys())
    catalogued_drafts = sorted(DRAFTS.keys() & KNOWN_CONFORMANCE_CLASSES.keys())

    assert checked_and_waived == []
    assert uncatalogued == []
    assert catalogued_drafts == []
