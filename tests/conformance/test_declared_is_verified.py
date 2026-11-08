"""Every requirement of a declared conformance class is checked or waived."""

import ast
from pathlib import Path

import pytest
from ogcapi_registry import KNOWN_CONFORMANCE_CLASSES, KNOWN_REQUIREMENTS, list_requirements

from tests.conformance.conftest import Served
from tests.conformance.requirements import CHECKED, DRAFTS, WAIVED


@pytest.fixture(name="declared", scope="module")
def list_declared_classes(served: Served) -> list[str]:
    """List the conformance classes a configuration declares.

    Parameters
    ----------
    served
        The configuration to ask.

    Returns
    -------
    list of str
        The URIs of ``/conformance``, with ``http://`` as the catalogue
        writes them.
    """
    response = served.client.get("/conformance", params={"f": "json"})
    return [uri.replace("https://", "http://", 1) for uri in response.json()["conformsTo"]]


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
