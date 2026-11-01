"""Vendor the OWASP API Security Top 10 ruleset for OpenLint.

The ruleset is Stoplight's, published for Spectral, and it imports
Spectral's own packages. OpenLint, the fork the lint workflow runs, ships
the same modules under ``@openlint/openlint-*`` and cannot resolve the
``@stoplight/spectral-*`` names. This script fetches the release we
reviewed, checks its digest, points those imports at OpenLint's packages
and writes a header that says so: the one place the patch is documented.

Run it to update the vendored copy after changing ``VERSION`` and
``SHA256`` to a release whose diff has been read.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from urllib.request import Request, urlopen

VERSION = "2.0.1"
SOURCE = f"https://unpkg.com/@stoplight/spectral-owasp-ruleset@{VERSION}/dist/ruleset.mjs"
SHA256 = "eb1824a973f326002a8c4eded1f98691ecf586e4091a4fdfdd6c00193e9497a7"
USER_AGENT = "fastgeoapi-vendor/1 (+https://github.com/geobeyond/fastgeoapi)"
TARGET = Path(".openlint/owasp-ruleset.mjs")
# Spectral's package -> the package OpenLint ships the same module under.
IMPORTS = {
    "@stoplight/spectral-core": "@openlint/openlint-core",
    "@stoplight/spectral-formats": "@openlint/openlint-formats",
    "@stoplight/spectral-functions": "@openlint/openlint-functions",
}


def rewrite_imports(source: str) -> str:
    """Point every Spectral import of ``source`` at OpenLint's package.

    Parameters
    ----------
    source
        The ruleset module as published.

    Returns
    -------
    str
        The module with each ``"@stoplight/spectral-*"`` import replaced.

    Raises
    ------
    ValueError
        When the module does not import one of the packages: the upstream
        changed shape, and its diff has to be read before vendoring it.
    """
    for spectral, openlint in IMPORTS.items():
        quoted = f'"{spectral}"'
        if quoted not in source:
            raise ValueError(f"{SOURCE} no longer imports {spectral}")
        source = source.replace(quoted, f'"{openlint}"')
    return source


def main() -> int:
    """Fetch, check, patch, write. Non-zero when the upstream is not the one reviewed."""
    # Fixed https URL, not user input: both suppressions are needed
    # because ruff (S310) and bandit (B310) each read only their own.
    request = Request(SOURCE, headers={"User-Agent": USER_AGENT})  # nosec B310
    with urlopen(request, timeout=30) as response:  # ruff: ignore[suspicious-url-open-usage] # nosec B310
        source = response.read()
    digest = hashlib.sha256(source).hexdigest()
    if digest != SHA256:
        print(f"{SOURCE} has sha256 {digest}, not the reviewed {SHA256}", file=sys.stderr)
        return 1
    try:
        patched = rewrite_imports(source.decode("utf-8"))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    header = (
        f"/* OWASP API Security Top 10 ruleset - vendored copy of {SOURCE}\n"
        f" * {len(source)} bytes, sha256 {SHA256}\n"
        " *\n"
        " * One patch, and only one: its imports of @stoplight/spectral-core,\n"
        " * -formats and -functions point at @openlint/openlint-core, -formats\n"
        " * and -functions, the same modules under the names OpenLint resolves.\n"
        " * Update with: uv run python scripts/vendor_owasp_ruleset.py\n"
        " */\n"
    )
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(header + patched, encoding="utf-8")
    print(f"wrote {TARGET} ({len(source)} bytes upstream, sha256 {digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
