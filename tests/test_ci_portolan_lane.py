"""The package that ingests Portolan catalogs has its own lane, on Python 3.10 and 3.12."""

import ast
import tomllib
from pathlib import Path

import yaml


def _rows() -> list[dict]:
    workflow = yaml.safe_load(Path(".github/workflows/tests.yml").read_text())
    return workflow["jobs"]["tests"]["strategy"]["matrix"]["include"]


def test_ci_runs_the_portolan_session_on_3_10_and_3_12():
    for python in ("3.10", "3.12"):
        assert {"python": python, "os": "ubuntu-22.04", "session": "portolan"} in _rows()


def test_nox_has_a_portolan_session_on_both_pythons():
    # Parsed, not run: running the noxfile imports nox, which the unlocked
    # lanes on main do not install.
    tree = ast.parse(Path("noxfile.py").read_text())
    (function,) = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "portolan"
    ]
    decorators = [ast.unparse(decorator) for decorator in function.decorator_list]

    assert "session(python=['3.10', '3.12'])" in decorators


def test_ci_runs_the_portolan_types_check():
    assert {"python": "3.12", "os": "ubuntu-22.04", "session": "portolan-types-check"} in _rows()


def test_nox_has_the_portolan_types_sessions():
    tree = ast.parse(Path("noxfile.py").read_text())
    decorators = {
        node.name: [ast.unparse(decorator) for decorator in node.decorator_list]
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }

    assert "session(name='portolan-types', python='3.12')" in decorators["portolan_types"]
    assert (
        "session(name='portolan-types-check', python='3.12')" in decorators["portolan_types_check"]
    )


def test_the_root_suite_collects_only_tests():
    # The package's own tests run in its lane, against the Pythons it supports.
    config = tomllib.loads(Path("pyproject.toml").read_text())

    assert config["tool"]["pytest"]["ini_options"]["testpaths"] == ["tests"]
