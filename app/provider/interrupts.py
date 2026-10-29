"""Stopping the work of a pygeoapi call once its request is cancelled.

pygeoapi runs a provider in a thread, and a thread cannot be cancelled.
When the request is cancelled, as uvicorn does with the requests still
running when its shutdown timeout runs out, the thread carries on until
the provider returns, and the process waits for it before exiting. A
provider that can stop its own work registers how with ``on_interrupt``,
and cancelling the request then stops that work too. DuckDB stops a
running query this way.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from contextvars import ContextVar

_current: ContextVar[Interrupts | None] = ContextVar("interrupts", default=None)


class CallInterruptedError(Exception):
    """The request was cancelled before this part of its work began."""


class Interrupts:
    """The ways to stop the work of one call, gathered in the thread that runs it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stops: list[Callable[[], object]] = []
        self._interrupted = False

    def run[T](self, call: Callable[..., T], *args) -> T:
        """``call(*args)``, with the ways to stop it gathered here."""
        token = _current.set(self)
        try:
            return call(*args)
        finally:
            # The thread goes back to its pool and runs other jobs.
            _current.reset(token)

    def add(self, stop: Callable[[], object]) -> None:
        """Keep ``stop``; once the call is interrupted, refuse the new work instead."""
        with self._lock:
            if not self._interrupted:
                self._stops.append(stop)
                return
        raise CallInterruptedError("the request was cancelled")

    def interrupt(self) -> None:
        """Stop the work registered so far, and refuse any that starts later."""
        with self._lock:
            self._interrupted = True
            stops, self._stops = self._stops, []
        for stop in stops:
            # Work that has already finished may refuse to be stopped.
            with suppress(Exception):
                stop()


def on_interrupt(stop: Callable[[], object]) -> None:
    """Register ``stop`` with the call running in this thread; outside a call, do nothing."""
    interrupts = _current.get()
    if interrupts is not None:
        interrupts.add(stop)
