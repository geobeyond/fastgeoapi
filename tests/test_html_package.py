"""The package of the HTML pages: where its files are, and the version it shares.

No ``app.*`` import in this module.
"""

import tomllib
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).parent.parent
PACKAGE = ROOT / "packages" / "fastgeoapi-html"


def test_the_package_points_at_its_own_directories():
    html = import_module("fastgeoapi_html")
    here = Path(html.__file__).parent

    assert (html.TEMPLATES, html.STATIC, html.LOCALE) == (
        here / "templates",
        here / "static",
        here / "locale",
    )


def test_the_italian_catalog_ships_with_the_package():
    html = import_module("fastgeoapi_html")

    assert (html.LOCALE / "it" / "LC_MESSAGES" / "messages.po").is_file()


def test_the_package_imports_nothing_from_fastgeoapi():
    sources = (PACKAGE / "fastgeoapi_html").rglob("*.py")
    lines = [line.strip() for path in sources for line in path.read_text().splitlines()]

    assert [line for line in lines if line.startswith(("import app", "from app"))] == []


def test_both_packages_carry_one_version():
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())
    html = tomllib.loads((PACKAGE / "pyproject.toml").read_text())
    version = root["project"]["version"]

    assert html["project"]["version"] == version
    assert root["project"]["optional-dependencies"]["html"] == [f"fastgeoapi-html=={version}"]


def test_a_version_bump_moves_the_package_and_the_pin():
    root = tomllib.loads((ROOT / "pyproject.toml").read_text())

    assert root["tool"]["commitizen"]["version_files"] == [
        "packages/fastgeoapi-html/pyproject.toml:^version",
        "pyproject.toml:fastgeoapi-html==",
    ]
