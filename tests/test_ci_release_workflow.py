"""The release publishes the package of the HTML pages next to fastgeoapi, pages included."""

import runpy
import shutil
from pathlib import Path

import yaml

HTML_PYPROJECT = Path("packages/fastgeoapi-html/pyproject.toml")


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


def test_the_pages_package_is_published_before_fastgeoapi():
    """fastgeoapi[html] pins the pages package: published first, the pin never points nowhere."""
    publishing = [step for step in _steps() if "gh-action-pypi-publish" in (step.get("uses") or "")]
    for on_testpypi in (True, False):
        steps = [
            step
            for step in publishing
            if ("test.pypi.org" in str(step.get("with") or {})) == on_testpypi
        ]
        directories = [(step.get("with") or {}).get("packages-dir", "dist/") for step in steps]
        assert directories == ["dist-html/", "dist/"], directories
        assert steps[0]["if"] == steps[1]["if"]


def test_a_development_version_moves_the_pages_package_and_its_pin(tmp_path):
    (tmp_path / HTML_PYPROJECT.parent).mkdir(parents=True)
    shutil.copy("pyproject.toml", tmp_path / "pyproject.toml")
    shutil.copy(HTML_PYPROJECT, tmp_path / HTML_PYPROJECT)
    bump = runpy.run_path(".github/scripts/dev_version.py")["bump"]

    version = bump(tmp_path, "1791999999")

    project = (tmp_path / "pyproject.toml").read_text()
    pages = (tmp_path / HTML_PYPROJECT).read_text()
    assert version.endswith(".dev1791999999")
    assert f'version = "{version}"' in project.splitlines()[:5]
    assert f'version = "{version}"' in pages
    assert f'"fastgeoapi-html=={version}"' in project


def test_the_development_release_bumps_through_that_script():
    assert _running("python .github/scripts/dev_version.py")
