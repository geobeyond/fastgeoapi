"""The package that ingests Portolan catalogs has its own lane, on Python 3.11 and 3.12."""

import ast
import re
import tomllib
from pathlib import Path

import yaml


def _rows() -> list[dict]:
    workflow = yaml.safe_load(Path(".github/workflows/tests.yml").read_text())
    return workflow["jobs"]["tests"]["strategy"]["matrix"]["include"]


def test_ci_runs_the_portolan_session_on_3_11_and_3_12():
    for python in ("3.11", "3.12"):
        assert {"python": python, "os": "ubuntu-22.04", "session": "portolan"} in _rows()


def test_nox_has_a_portolan_session_on_both_pythons():
    # Parsed, not run: running the noxfile imports nox, which the unlocked
    # lanes on main do not install.
    tree = ast.parse(Path("noxfile.py").read_text())
    (function,) = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "portolan"
    ]
    decorators = [ast.unparse(decorator) for decorator in function.decorator_list]

    assert "session(python=['3.11', '3.12'])" in decorators


def test_the_lane_starts_at_the_oldest_python_the_package_supports():
    package = tomllib.loads(Path("packages/fastgeoapi-portolan/pyproject.toml").read_text())
    oldest = package["project"]["requires-python"].removeprefix(">=")
    lanes = {row["python"] for row in _rows() if row["session"] in ("portolan", "portolan-rashid")}

    assert min(lanes, key=lambda version: tuple(map(int, version.split(".")))) == oldest


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


def test_ci_runs_the_rashid_agreement_on_3_11_and_3_12():
    for python in ("3.11", "3.12"):
        assert {"python": python, "os": "ubuntu-22.04", "session": "portolan-rashid"} in _rows()


def test_nox_has_a_portolan_rashid_session_on_both_pythons():
    # portolan-cli pins an older rashid, so the comparison has a session of its own.
    tree = ast.parse(Path("noxfile.py").read_text())
    (function,) = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "portolan_rashid"
    ]
    decorators = [ast.unparse(decorator) for decorator in function.decorator_list]

    assert "session(name='portolan-rashid', python=['3.11', '3.12'])" in decorators


def test_the_portolan_session_installs_portolan_cli_with_command_plugins():
    # Command plugins are on portolan-cli's main branch only, so the session
    # installs one of its commits until a release ships them; from PyPI the
    # plugin test would skip.
    tree = ast.parse(Path("noxfile.py").read_text())
    (function,) = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "portolan"
    ]
    installed = [
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("portolan-cli")
    ]

    (requirement,) = installed
    assert re.fullmatch(
        r"portolan-cli @ git\+https://github\.com/portolan-sdi/portolan-cli@[0-9a-f]{40}",
        requirement,
    )
