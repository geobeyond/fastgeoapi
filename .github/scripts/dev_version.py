"""The version of a development release, written into fastgeoapi and the packages it pins.

The release on develop publishes to TestPyPI one patch above the current
version, with a ``.dev`` stamp. The html and portolan extras each pin
their package to an exact version, so the three projects and both pins
move together.
"""

import re
import time
from pathlib import Path

PACKAGES = ("fastgeoapi-html", "fastgeoapi-portolan")
_VERSION = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)


def bump(root: Path, stamp: str) -> str:
    """Write the development version into the projects under ``root`` and return it."""
    project = root / "pyproject.toml"
    text = project.read_text()
    found = _VERSION.search(text)
    if found is None:
        raise SystemExit(f"{project} names no version")
    major, minor, patch = found.group(1).split(".")[:3]
    version = f"{major}.{minor}.{int(patch) + 1}.dev{stamp}"
    text = _VERSION.sub(f'version = "{version}"', text, count=1)
    for name in PACKAGES:
        text = re.sub(rf'"{name}==[^"]+"', f'"{name}=={version}"', text)
        package = root / "packages" / name / "pyproject.toml"
        package.write_text(_VERSION.sub(f'version = "{version}"', package.read_text(), count=1))
    project.write_text(text)
    return version


if __name__ == "__main__":
    print(f"Publishing version: {bump(Path.cwd(), str(int(time.time())))}")
