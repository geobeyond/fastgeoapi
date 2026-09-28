"""The renderer tests have a nox session and a CI lane on Ubuntu 24.04."""

import runpy
from pathlib import Path

import yaml


def _job() -> dict:
    return yaml.safe_load(Path(".github/workflows/tests.yml").read_text())["jobs"]["tests"]


def test_ci_runs_the_maps_session_on_ubuntu_24_04():
    rows = _job()["strategy"]["matrix"]["include"]

    assert {"python": "3.12", "os": "ubuntu-24.04", "session": "maps"} in rows


def test_ci_installs_the_renderer_libraries_for_that_lane():
    steps = [s for s in _job()["steps"] if s.get("if") == "matrix.session == 'maps'"]

    assert steps and "mesa-vulkan-drivers" in steps[0]["run"] and "libicu74" in steps[0]["run"]


def test_nox_has_a_maps_session():
    assert callable(runpy.run_path("noxfile.py").get("maps"))
