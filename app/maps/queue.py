"""One renderer and the maps that wait for it.

A map provider composes a queue with its renderer factory. The renderer
is built at the first map, in a thread, and draws one map at a time
behind a semaphore. How many maps wait, and for how long, the route
decides before the provider is called. ``render_limit`` bounds the
render; past it, or after any failure, the renderer is replaced.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from app.config.logging import create_logger
from app.maps.contract import MapRenderer, MapRequest, RenderError

logger = create_logger("app.maps.queue")


class DrawTimeoutError(Exception):
    """The render went past ``render_limit``."""


class RenderQueue:
    """One renderer, built at the first map, and the maps that wait for it."""

    def __init__(
        self,
        factory: Callable[[], MapRenderer],
        *,
        render_limit: float,
    ) -> None:
        """``factory`` builds the renderer; it runs in a thread, at the first map."""
        self._factory = factory
        self._render_limit = render_limit
        self._renderer: MapRenderer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Bound to the loop of its first wait, as any asyncio primitive since 3.10.
        self._semaphore = asyncio.Semaphore(1)
        self._waiting = 0
        self._closing: set[asyncio.Task] = set()
        self._closed = False

    @property
    def renderer_is_built(self) -> bool:
        """Whether a renderer is currently alive."""
        return self._renderer is not None

    @property
    def waiting(self) -> int:
        """How many maps are being drawn or are waiting for the renderer."""
        return self._waiting

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The event loop that owns the renderer, once a map has been drawn."""
        return self._loop

    async def draw(self, request: MapRequest) -> bytes:
        """The PNG of ``request``.

        Raises :class:`DrawTimeoutError` past ``render_limit``, or
        :class:`~app.maps.contract.RenderError` when the renderer fails;
        what the factory raises reaches the caller as it is.
        """
        self._loop = asyncio.get_running_loop()
        self._waiting += 1
        try:
            return await self._draw(request)
        finally:
            self._waiting -= 1
            # After close(), the renderer goes as soon as nothing is left to draw:
            # maps queued before the close may have built it again.
            if self._closed and self._waiting == 0 and self._renderer is not None:
                self._discard(self._renderer)

    async def _draw(self, request: MapRequest) -> bytes:
        async with self._semaphore:
            return await self._render(request)

    async def _render(self, request: MapRequest) -> bytes:
        if self._renderer is None:
            # In a thread: the first build imports the renderer's modules and looks
            # up its binary on disk.
            self._renderer = await asyncio.to_thread(self._factory)
        renderer = self._renderer
        try:
            return await asyncio.wait_for(renderer.render(request), timeout=self._render_limit)
        except TimeoutError as error:
            self._discard(renderer)
            logger.warning("map render went past render_limit; the renderer is replaced")
            raise DrawTimeoutError() from error
        except Exception as error:
            # Any failure counts as a broken renderer. Its message may name
            # the signed URL of the data, so only its type reaches the log, and
            # the chain is dropped before the error travels to a client.
            self._discard(renderer)
            logger.warning(f"map renderer failed with {type(error).__name__}; it is replaced")
            raise RenderError("the map renderer failed") from None

    def _discard(self, renderer: MapRenderer) -> None:
        if self._renderer is renderer:
            self._renderer = None
        task = asyncio.get_running_loop().create_task(renderer.aclose())
        # The loop keeps only a weak reference to a task.
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def aclose(self) -> None:
        """The async twin of :meth:`close`, which also waits for the renderer to close."""
        self._closed = True
        if self._waiting == 0 and self._renderer is not None:
            self._discard(self._renderer)
        if self._closing:
            await asyncio.gather(*self._closing, return_exceptions=True)

    def close(self) -> None:
        """Close the renderer once no map is being drawn or waiting for it.

        Safe to call from any thread: the plugin cache calls it on reload,
        while the old sub-app may still be serving maps with this queue.
        """
        self._closed = True
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        async def close_if_idle() -> None:
            if self._waiting == 0 and self._renderer is not None:
                self._discard(self._renderer)

        asyncio.run_coroutine_threadsafe(close_if_idle(), loop)
