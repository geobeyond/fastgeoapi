"""The mlnative binding: MapLibre Native, from the mlnative fork, as a renderer process.

:func:`create_renderer` is the map provider's default ``renderer``. It finds
mlnative and its binary and hands ``mlnative.AsyncRenderer`` to a
:class:`~app.maps.renderer.ProcessRenderer` as its process type.
"""

from __future__ import annotations

import importlib
import logging
from functools import partial
from typing import Any

from app.maps.renderer import ProcessRenderer, RedactQueries

MISSING = (
    "MapLibre Native is not installed: map rendering needs the maps dependency group "
    "(uv sync --group maps), on Linux"
)


def _mlnative() -> tuple[Any, str]:
    """The mlnative module and the path of its renderer binary."""
    try:
        module = importlib.import_module("mlnative")
    except ImportError as error:
        raise ImportError(MISSING) from error
    try:
        binary = str(module.get_binary_path())
    except Exception as error:
        raise ImportError(f"{MISSING}; the installed mlnative has no renderer binary") from error
    return module, binary


def create_renderer(options: dict[str, Any]) -> ProcessRenderer:
    """The renderer a map provider builds at its first map.

    The provider's ``renderer`` option names it by default. Raises
    :class:`ImportError` when mlnative or its binary is missing.
    """
    module, binary = _mlnative()
    timeout = float(options.get("timeout", 30))
    limit = float(options.get("render_limit") or 4 * timeout)
    for name in ("mlnative._bridge", "mlnative.aio"):
        log = logging.getLogger(name)
        if not any(isinstance(item, RedactQueries) for item in log.filters):
            log.addFilter(RedactQueries())
    return ProcessRenderer(
        # The binary is looked up here, in the thread that builds the renderer: the
        # lookup stats a file, which the process start would otherwise do on the loop.
        # The process waits a little longer than the provider's render_limit,
        # past which the provider replaces the renderer: the process's own
        # timeout is only a backstop.
        process=partial(module.AsyncRenderer, command=[binary], timeout=limit + 5),
        max_rss_mb=float(options.get("max_rss_mb", 600)),
    )
