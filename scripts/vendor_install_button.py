"""Vendor install.apicommons.org's <mcp-install-button> into the docs.

The original derives the chooser's origin from the directory of its own
``<script src>``, falling back to ``https://install.apicommons.org``
only when that is unavailable. Served from our documentation site it
would therefore point every link at our site, where no chooser lives.
This script fetches the file, checks it is the one we reviewed, replaces
that single expression with the constant, and writes a header that says
so — the one place the patch is documented.

Run it to update the vendored copy; if the expression is no longer
found, the upstream changed shape and the diff has to be read by a
person before anything is written.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

SOURCE = "https://install.apicommons.org/button.js"
# The host answers 403 to urllib's default User-Agent; say who we are.
USER_AGENT = "fastgeoapi-vendor/1 (+https://github.com/geobeyond/fastgeoapi)"
TARGET = Path("docs/javascripts/mcp-install-button.js")
# The expression the original uses to locate the chooser.
ORIGINAL = (
    'const y=(()=>{const e=document.currentScript?.src;try{return e?new URL(".",e)'
    '.href.replace(/\\/$/,""):"https://install.apicommons.org"}catch{return'
    '"https://install.apicommons.org"}})()'
)
PATCHED = 'const y="https://install.apicommons.org"'


def main() -> int:
    """Fetch, check, patch, write. Non-zero when the upstream changed shape."""
    # Fixed https URL, not user input: both suppressions are needed
    # because ruff (S310) and bandit (B310) each read only their own.
    request = Request(SOURCE, headers={"User-Agent": USER_AGENT})  # nosec B310
    with urlopen(request, timeout=30) as response:  # ruff: ignore[suspicious-url-open-usage] # nosec B310
        source = response.read()
    digest = hashlib.sha256(source).hexdigest()
    text = source.decode("utf-8")
    if text.count(ORIGINAL) != 1:
        print(
            f"{SOURCE} no longer contains the chooser-origin expression exactly once; "
            "read the upstream diff before vendoring it",
            file=sys.stderr,
        )
        return 1
    header = (
        f"/* <mcp-install-button> - vendored copy of {SOURCE}\n"
        f" * fetched {datetime.now(UTC).date().isoformat()}, {len(source)} bytes, "
        f"sha256 {digest}\n"
        " *\n"
        " * One patch, and only one: the original derives the chooser's origin\n"
        " * from its own <script src> directory, which served from this site\n"
        " * would point every link at this site. Here that expression is the\n"
        " * constant https://install.apicommons.org. The chooser this button\n"
        " * opens is hosted there; this file only decides what runs on our\n"
        " * pages. Update with: uv run python scripts/vendor_install_button.py\n"
        " */\n"
    )
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(header + text.replace(ORIGINAL, PATCHED), encoding="utf-8")
    print(f"wrote {TARGET} ({len(source)} bytes upstream, sha256 {digest})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
