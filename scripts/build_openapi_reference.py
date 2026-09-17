"""Dereference an OpenAPI document for the build-time API reference.

`oad gen-docs` (essentials-openapi) does not resolve remote ``$ref``s: it
treats ``https://schemas.opengis.net/...`` as a local path and fails on
the first one. fastgeoapi already has a resolver for the same problem —
the MCP tools are generated from a dereferenced document — so this
script reuses it and writes the result where the docs build can read it.

Usage::

    uv run python scripts/build_openapi_reference.py               # live demo document
    uv run python scripts/build_openapi_reference.py openapi.json  # a local document

Output: ``docs_build/openapi-resolved.json`` (gitignored). The count of
dangling ``#/$defs`` references it prints is the resolver defect tracked
alongside this work: inlined documents keep their document-local pointers.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

from app.utils.openapi_resolver import count_external_refs, resolve_external_refs

LIVE = "https://fastgeoapi.fly.dev/geoapi/openapi?f=json"
OUTPUT = Path("docs_build/openapi-resolved.json")
CACHE = Path("docs_build/openapi-refs-cache")


def load(source: str) -> dict:
    """The document, from a local path or from the live demo."""
    if Path(source).is_file():
        return json.loads(Path(source).read_text(encoding="utf-8"))
    # A fixed https URL or a path the operator typed, not untrusted input.
    with urllib.request.urlopen(source, timeout=30) as response:  # ruff: ignore[suspicious-url-open-usage] # nosec B310
        return json.load(response)


def main(argv: list[str]) -> int:
    """Resolve, report, write."""
    source = argv[1] if len(argv) > 1 else LIVE
    document = load(source)
    before = count_external_refs(document)
    started = time.perf_counter()
    resolved = resolve_external_refs(document, cache_dir=CACHE)
    elapsed = time.perf_counter() - started
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(resolved), encoding="utf-8")
    dangling = json.dumps(resolved).count('"$ref": "#/$defs/')
    print(
        f"{source}: {before} remote refs -> {count_external_refs(resolved)} in {elapsed:.1f}s; "
        f"wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes); "
        f"dangling #/$defs refs left by inlining: {dangling}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
