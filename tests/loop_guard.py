"""A blockbuster guard for the event loop that also watches the storage layer.

blockbuster wraps the Python functions that block: sockets, files, sleep.
obstore does its I/O in Rust, so a synchronous obstore read made on the
loop gets past it. The app reaches obstore only through the storage
layer's backend, so the guard watches that backend's synchronous methods.
"""

import importlib
from collections.abc import Iterator
from contextlib import contextmanager

from blockbuster import BlockBuster, BlockBusterFunction, blockbuster_ctx

SYNC_STORE_METHODS = (
    "get",
    "get_range",
    "get_ranges",
    "head",
    "put",
    "keys",
    "entries",
    "delete",
    "sign",
)
"""The backend's synchronous methods that can wait on the store."""


@contextmanager
def loop_guard() -> Iterator[BlockBuster]:
    """Fail on any blocking call made on the event loop, the storage layer's included."""
    # The live class: another test module may have purged app.* and imported it again.
    store = importlib.import_module("app.provider.storage.obstore_").ObstoreStore
    with blockbuster_ctx() as blockbuster:
        watched = [BlockBusterFunction(store, name).activate() for name in SYNC_STORE_METHODS]
        try:
            yield blockbuster
        finally:
            for function in watched:
                function.deactivate()
