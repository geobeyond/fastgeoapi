"""The release publishes fastgeoapi with the two packages it pins: the HTML pages and the Portolan ingest."""

import re
import runpy
import shutil
import tomllib
from pathlib import Path

import yaml

HTML_PYPROJECT = Path("packages/fastgeoapi-html/pyproject.toml")
PORTOLAN_PYPROJECT = Path("packages/fastgeoapi-portolan/pyproject.toml")


def _steps() -> list[dict]:
    workflow = yaml.safe_load(Path(".github/workflows/release.yml").read_text())
    return workflow["jobs"]["release"]["steps"]


def _running(fragment: str) -> list[tuple[int, dict]]:
    return [(i, step) for i, step in enumerate(_steps()) if fragment in (step.get("run") or "")]


def test_the_pages_package_is_built_in_a_directory_of_its_own():
    assert _running("python -m build packages/fastgeoapi-html --outdir dist-html")


def test_a_pages_wheel_without_its_manifest_is_refused():
    ((_, step),) = _running("fastgeoapi_html/static/.vite/manifest.json")

    assert "dist-html/" in step["run"]
    assert "exit 1" in step["run"]


def test_the_portolan_package_is_built_in_a_directory_of_its_own():
    assert _running("python -m build packages/fastgeoapi-portolan --outdir dist-portolan")


def test_the_packages_are_published_before_fastgeoapi():
    """Both extras pin these packages, so they go out first and no pin names a version not there yet."""
    publishing = [step for step in _steps() if "gh-action-pypi-publish" in (step.get("uses") or "")]
    for on_testpypi in (True, False):
        steps = [
            step
            for step in publishing
            if ("test.pypi.org" in str(step.get("with") or {})) == on_testpypi
        ]
        directories = [(step.get("with") or {}).get("packages-dir", "dist/") for step in steps]
        assert directories == ["dist-html/", "dist-portolan/", "dist/"], directories
        assert len({step["if"] for step in steps}) == 1


def test_a_development_version_moves_both_packages_and_their_pins(tmp_path):
    for package in (HTML_PYPROJECT, PORTOLAN_PYPROJECT):
        (tmp_path / package.parent).mkdir(parents=True)
        shutil.copy(package, tmp_path / package)
    shutil.copy("pyproject.toml", tmp_path / "pyproject.toml")
    bump = runpy.run_path(".github/scripts/dev_version.py")["bump"]

    version = bump(tmp_path, "1791999999")

    project = (tmp_path / "pyproject.toml").read_text()
    assert version.endswith(".dev1791999999")
    assert f'version = "{version}"' in project.splitlines()[:5]
    for package in (HTML_PYPROJECT, PORTOLAN_PYPROJECT):
        assert f'version = "{version}"' in (tmp_path / package).read_text()
        assert f'"{package.parent.name}=={version}"' in project


def test_commitizen_bumps_both_packages_and_pins(tmp_path):
    """``version_files`` applied the way ``cz bump`` does: on each line its regex matches, the version moves."""
    for package in (HTML_PYPROJECT, PORTOLAN_PYPROJECT):
        (tmp_path / package.parent).mkdir(parents=True)
        shutil.copy(package, tmp_path / package)
    shutil.copy("pyproject.toml", tmp_path / "pyproject.toml")
    config = tomllib.loads(Path("pyproject.toml").read_text())
    current = config["project"]["version"]
    for entry in config["tool"]["commitizen"]["version_files"]:
        name, pattern = entry.split(":", 1)
        target = tmp_path / name
        lines = [
            line.replace(current, "9.9.9") if re.search(pattern, line) else line
            for line in target.read_text().splitlines(keepends=True)
        ]
        target.write_text("".join(lines))

    project = (tmp_path / "pyproject.toml").read_text()
    for package in (HTML_PYPROJECT, PORTOLAN_PYPROJECT):
        bumped = tomllib.loads((tmp_path / package).read_text())
        assert bumped["project"]["version"] == "9.9.9"
        assert f'"{package.parent.name}==9.9.9"' in project


def test_the_development_release_bumps_through_that_script():
    assert _running("python .github/scripts/dev_version.py")
