"""The compiled assets of the pages, found through Vite's manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.config.logging import create_logger

logger = create_logger("app.html.assets")

STYLE = "pages/style.css"
"""The manifest entry of the stylesheet every page loads."""

IMMUTABLE = "public, max-age=31536000, immutable"
"""The cache of a compiled file: its name changes whenever its content does."""


class Assets:
    """The URLs of the files of manifest entries, under ``/_html/`` of the server."""

    def __init__(self, static: Path, base_url: str) -> None:
        """Read the manifest Vite wrote in ``static``; none means nothing to link."""
        manifest = static / ".vite" / "manifest.json"
        self._chunks: dict[str, Any] = (
            json.loads(manifest.read_text()) if manifest.is_file() else {}
        )
        if not self._chunks:
            logger.warning(f"no compiled assets in {static}: the pages have no style nor islands")
        self._base = f"{base_url.rstrip('/')}/_html/"

    def styles(self, entries: tuple[str, ...]) -> list[str]:
        """The stylesheets of ``entries`` and of the chunks they import, each once, in order."""
        files: list[str] = []
        seen: set[str] = set()
        pending = list(entries)
        while pending:
            name = pending.pop(0)
            if name in seen or name not in self._chunks:
                continue
            seen.add(name)
            chunk = self._chunks[name]
            own = [chunk["file"]] if chunk["file"].endswith(".css") else []
            for file in [*own, *chunk.get("css", [])]:
                if file not in files:
                    files.append(file)
            pending.extend(chunk.get("imports", []))
        return [self._base + file for file in files]

    def scripts(self, entries: tuple[str, ...]) -> list[str]:
        """The script of each entry that has one; the chunks it imports load on their own."""
        files = [self._chunks[name]["file"] for name in entries if name in self._chunks]
        return [self._base + file for file in files if file.endswith(".js")]


class ImmutableFiles(StaticFiles):
    """The compiled assets, kept by browsers and caches for a year."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Starlette's answer, marked immutable when it is the file."""
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = IMMUTABLE
        return response
