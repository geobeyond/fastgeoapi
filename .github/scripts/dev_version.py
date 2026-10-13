"""The version of a development release, written into fastgeoapi and its pages package.

The release on develop publishes to TestPyPI one patch above the current
version, with a ``.dev`` stamp. fastgeoapi[html] pins the pages package to
an exact version, so both projects and the pin move together.
"""

import re
import time
from pathlib import Path

PAGES = Path("packages/fastgeoapi-html/pyproject.toml")
_VERSION = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)
_PIN = re.compile(r'"fastgeoapi-html==[^"]+"')


def bump(root: Path, stamp: str) -> str:
    """Write the development version into the two projects under ``root`` and return it."""
    project = root / "pyproject.toml"
    text = project.read_text()
    found = _VERSION.search(text)
    if found is None:
        raise SystemExit(f"{project} names no version")
    major, minor, patch = found.group(1).split(".")[:3]
    version = f"{major}.{minor}.{int(patch) + 1}.dev{stamp}"
    text = _VERSION.sub(f'version = "{version}"', text, count=1)
    project.write_text(_PIN.sub(f'"fastgeoapi-html=={version}"', text))
    pages = root / PAGES
    pages.write_text(_VERSION.sub(f'version = "{version}"', pages.read_text(), count=1))
    return version


if __name__ == "__main__":
    print(f"Publishing version: {bump(Path.cwd(), str(int(time.time())))}")
