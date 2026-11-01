"""The OWASP ruleset vendored for OpenLint, and the files the lint workflow names."""

import importlib.util
import re
from pathlib import Path

import pytest
import yaml


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "vendor_owasp_ruleset", Path("scripts/vendor_owasp_ruleset.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


UPSTREAM = """import { truthy } from "@stoplight/spectral-functions";
import { oas3 } from "@stoplight/spectral-formats";
import { createRulesetFunction } from "@stoplight/spectral-core";
export default { formats: [oas3], rules: {} };
"""


def test_every_spectral_import_points_at_openlint(script):
    patched = script.rewrite_imports(UPSTREAM)

    assert "@stoplight/" not in patched
    assert re.findall(r'from "([^"]+)"', patched) == [
        "@openlint/openlint-functions",
        "@openlint/openlint-formats",
        "@openlint/openlint-core",
    ]


def test_a_ruleset_without_one_of_the_imports_is_refused(script):
    without_formats = UPSTREAM.replace("@stoplight/spectral-formats", "./formats.js")

    with pytest.raises(ValueError, match="@stoplight/spectral-formats"):
        script.rewrite_imports(without_formats)


def test_the_vendored_ruleset_imports_nothing_from_spectral(script):
    vendored = script.TARGET.read_text()

    imported = re.findall(r'from "([^"]+)"', vendored)
    assert imported
    assert not [name for name in imported if name.startswith("@stoplight/")]
    assert script.SHA256 in vendored.split("*/", 1)[0]


def test_the_owasp_ruleset_extends_the_vendored_copy(script):
    ruleset = yaml.safe_load(Path(".openlint.owasp-top-10.yaml").read_text())

    assert ruleset["extends"] == [f"./{script.TARGET.as_posix()}"]


def test_every_ruleset_the_workflow_names_exists():
    workflow = Path(".github/workflows/openapi.yml").read_text()

    named = set(re.findall(r"--ruleset\s+(\S+)", workflow))

    assert named == {".openlint.oas3.yaml", ".openlint.owasp-top-10.yaml"}
    assert all(Path(name).is_file() for name in named)
    assert "spectral" not in workflow.lower()
