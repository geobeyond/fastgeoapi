"""Zensical macros for the documentation build.

``generate_openapi`` renders an OpenAPI document as Markdown with ``oad``
(essentials-openapi), so the API reference is part of the site — themed,
indexed by search, no client-side script — rather than a Swagger UI
mounted at runtime. The shape comes from waldemarlehner/zensical-oapi-poc;
the dependency is essentials-openapi, taken straight.

The document must be *dereferenced* first
(``scripts/build_openapi_reference.py``): ``oad`` does not resolve remote
``$ref``s. Zensical's ``macros`` plugin loads this module from the project
root; only pages with ``render_macros: true`` see it.

Both failure modes degrade to an admonition on the page rather than a
failed build, so a docs pipeline without ``oad`` or without the resolved
document still publishes everything else.
"""

from __future__ import annotations

import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import tempfile
import time
from pathlib import Path
from typing import Any


def define_env(env: Any) -> None:
    """Register the macros the pages may call."""

    @env.macro
    def generate_openapi(oas_path: str) -> str:
        """Render the OpenAPI document at ``oas_path`` as MkDocs Markdown."""
        path = Path(oas_path)
        if not path.is_absolute():
            path = Path(env.conf["root_dir"]) / path
        if not path.is_file():
            return (
                '!!! danger "OpenAPI document not found"\n\n'
                f"    `{path}` — run `uv run python scripts/build_openapi_reference.py` first.\n"
            )
        oad = shutil.which("oad")
        if oad is None:
            return (
                '!!! danger "`oad` is not installed"\n\n'
                '    Build with `uv run --with "essentials-openapi[full]" zensical build`.\n'
            )
        started = time.perf_counter()
        with tempfile.NamedTemporaryFile(suffix=".md") as out:
            subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]
                [oad, "gen-docs", "-s", str(path.resolve()), "-d", out.name],
                check=True,
                capture_output=True,
            )
            markdown = Path(out.name).read_text(encoding="utf-8")
        print(
            f"[openapi-reference] oad rendered {path.name}: {len(markdown)} chars "
            f"in {time.perf_counter() - started:.2f}s"
        )
        return markdown
