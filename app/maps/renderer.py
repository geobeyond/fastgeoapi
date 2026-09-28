"""Maps drawn through one external renderer process that takes a GL camera.

One process draws the maps of one provider, resized to each map so that
every size up to the provider's limit uses it. The style goes to the
process again only when it changes: another named style, the background
left out, or a renewed signed URL. The process starts at the first map and
is replaced after any failure, or after a map that leaves it above
``max_rss_mb``.

The process takes a centre and a zoom, as MapLibre Native does, and a style
as a JSON string. A binding module supplies its type:
:mod:`app.maps.mlnative` for the mlnative fork.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from app.config.logging import create_logger
from app.maps.camera import camera_for_bbox
from app.maps.contract import MapRequest, RenderError

logger = create_logger("app.maps.renderer")

_QUERY = re.compile(r"\?[^\s\"'<>]*")


def redact(text: str) -> str:
    """``text`` with URL query strings cut: a presigned URL carries its signature there."""
    return _QUERY.sub("?<redacted>", text)


class RedactQueries(logging.Filter):
    """Cuts the query strings from the records of a renderer library's own loggers."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep the record, with its message redacted."""
        record.msg, record.args = redact(record.getMessage()), None
        return True


class RendererProcess(Protocol):
    """A renderer process driven by a GL camera, such as ``mlnative.AsyncRenderer``."""

    @property
    def pid(self) -> int | None:
        """The process id while the process runs."""
        ...

    async def start(self) -> None:
        """Start the process and load the style."""
        ...

    async def render(self, center: Any, zoom: float, *, size: Any, output: Any) -> Any:
        """Draw one view at ``size``: PNG bytes, or raw pixels with ``output="rgba"``."""
        ...

    async def reload_style(self, style: str) -> None:
        """Replace the style without restarting the process."""
        ...

    async def aclose(self) -> None:
        """Stop the process."""
        ...


ProcessFactory = Callable[[int, int, str], RendererProcess]
"""Builds a process for a width, a height and a style. A binding passes its
process type here, with its own options bound."""


def rss_mb(pid: int) -> float | None:
    """The resident memory of process ``pid`` in MB, or None where ``/proc`` cannot tell."""
    try:
        status = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return None


def _stretch(raw: Any, size: tuple[int, int]) -> bytes:
    """Resample RGBA pixels to ``size`` and encode a PNG: the stretch a WMS GetMap makes."""
    image = Image.frombytes("RGBA", (raw.width, raw.height), raw.data)
    buffer = io.BytesIO()
    image.resize(size, Image.Resampling.BILINEAR).save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


class ProcessRenderer:
    """A map renderer that draws through one renderer process."""

    def __init__(
        self,
        *,
        process: ProcessFactory,
        max_rss_mb: float = 600,
        rss: Callable[[int], float | None] = rss_mb,
    ) -> None:
        """``process`` builds a renderer process for a size and a style."""
        self._new_process = process
        self._max_rss_mb = float(max_rss_mb)
        self._rss = rss
        self._process: RendererProcess | None = None
        self._style: str | None = None
        self._lock = asyncio.Lock()

    @property
    def pid(self) -> int | None:
        """The id of the renderer process while one runs."""
        return self._process.pid if self._process is not None else None

    async def render(self, request: MapRequest) -> bytes:
        """The PNG of ``request``, drawn at the camera's size.

        When the aspect of the bbox differs from the image's, the render is
        stretched to the image.
        """
        camera = camera_for_bbox(request.bbox, request.width, request.height)
        image = (request.width, request.height)
        style = json.dumps(request.style, separators=(",", ":"))
        center = list(camera.center)
        async with self._lock:
            try:
                process = await self._ready(style, camera.size)
                if camera.size == image:
                    png = await process.render(center, camera.zoom, size=camera.size, output="png")
                else:
                    raw = await process.render(center, camera.zoom, size=camera.size, output="rgba")
                    png = await asyncio.to_thread(_stretch, raw, image)
            except Exception as error:
                logger.warning(f"map renderer process failed: {redact(str(error))}")
                await self._drop()
                raise RenderError(f"the renderer failed with {type(error).__name__}") from None
            await self._check_memory()
            return png

    async def aclose(self) -> None:
        """Stop the renderer process."""
        await self._drop()

    async def _ready(self, style: str, size: tuple[int, int]) -> RendererProcess:
        if self._process is None:
            process = self._new_process(size[0], size[1], style)
            self._process, self._style = process, style
            await process.start()
            return process
        if style != self._style:
            await self._process.reload_style(style)
            self._style = style
        return self._process

    async def _check_memory(self) -> None:
        pid = self.pid
        if pid is None:
            return
        used = await asyncio.to_thread(self._rss, pid)
        if used is not None and used > self._max_rss_mb:
            logger.info(
                f"map renderer process at {used:.0f} MB, above max_rss_mb "
                f"{self._max_rss_mb:.0f}; it is replaced"
            )
            await self._drop()

    async def _drop(self) -> None:
        process, self._process, self._style = self._process, None, None
        if process is not None:
            with suppress(Exception):
                await process.aclose()
