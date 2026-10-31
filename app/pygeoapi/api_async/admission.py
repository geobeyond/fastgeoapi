"""How many maps a provider draws at once, how many wait, and for how long.

The route admits a map before calling the provider, with the limits the
provider declares, so every engine gets the same 503 and 504. A map
whose client is still waiting past the timeout answers 504, but its draw
goes on and keeps its slot until the engine finishes: cancelling a draw
may kill the engine's process, and with it what the engine has cached.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Awaitable, Callable

from app.interfaces.providers import MapLimits
from app.provider.maps import MapRendererBusyError, MapRenderTimeoutError

_ADMISSIONS: weakref.WeakKeyDictionary[object, MapAdmission] = weakref.WeakKeyDictionary()


class MapAdmission:
    """The slots of one provider instance: the maps it draws and those that wait."""

    def __init__(self, *, concurrent: int, waiting: int, timeout: float) -> None:
        """Set up the slots of one provider instance.

        Parameters
        ----------
        concurrent
            How many maps draw at the same time.
        waiting
            How many more maps may wait for a slot; one more answers 503.
        timeout
            How many seconds a map may take, the wait included; a longer one
            answers 504.
        """
        self._capacity = concurrent + waiting
        self._timeout = timeout
        # Bound to the loop of its first wait, as any asyncio primitive since 3.10.
        self._drawing = asyncio.Semaphore(concurrent)
        self._occupied = 0
        self._draws: set[asyncio.Task] = set()

    @property
    def occupied(self) -> int:
        """How many maps are drawing or waiting."""
        return self._occupied

    async def run(self, draw: Callable[[], Awaitable[bytes]]) -> bytes:
        """Draw a map once a slot is free.

        Parameters
        ----------
        draw
            Starts the draw; it is called once the map has a slot.

        Returns
        -------
        bytes
            The map.

        Raises
        ------
        MapRendererBusyError
            When every slot is taken; the route answers 503 with
            ``Retry-After``.
        MapRenderTimeoutError
            When the map takes longer than the timeout, the wait included;
            the route answers 504.
        """
        if self._occupied >= self._capacity:
            raise MapRendererBusyError()
        self._occupied += 1
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        try:
            await asyncio.wait_for(self._drawing.acquire(), self._timeout)
        except TimeoutError:
            self._occupied -= 1
            raise MapRenderTimeoutError() from None
        except BaseException:
            self._occupied -= 1
            raise
        task = loop.create_task(_awaited(draw))
        self._draws.add(task)
        task.add_done_callback(self._release)
        try:
            return await asyncio.wait_for(asyncio.shield(task), max(0.0, deadline - loop.time()))
        except TimeoutError:
            raise MapRenderTimeoutError() from None

    def _release(self, task: asyncio.Task) -> None:
        self._draws.discard(task)
        self._drawing.release()
        self._occupied -= 1
        # A draw that outlived its map fails with nobody awaiting it; reading
        # its error keeps asyncio quiet.
        if not task.cancelled():
            task.exception()


async def _awaited(draw: Callable[[], Awaitable[bytes]]) -> bytes:
    return await draw()


def admission_for(provider: object, limits: MapLimits) -> MapAdmission:
    """The admission of one provider instance, made with ``limits`` the first time.

    A reload builds new provider instances, so they start with empty
    admissions while the old ones let their draws end.

    Parameters
    ----------
    provider
        The provider instance.
    limits
        The collection's limits; only ``concurrent``, ``waiting`` and
        ``timeout`` count here.

    Returns
    -------
    MapAdmission
        The same admission for the same instance.
    """
    admission = _ADMISSIONS.get(provider)
    if admission is None:
        admission = MapAdmission(
            concurrent=limits.concurrent, waiting=limits.waiting, timeout=limits.timeout
        )
        _ADMISSIONS[provider] = admission
    return admission
