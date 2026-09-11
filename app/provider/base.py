"""The async surface fastgeoapi adds beside pygeoapi's provider contract (ADR-0010).

pygeoapi's contract is synchronous and lives in its root classes
(``BaseProvider``, ``BaseMVTProvider``): the API layer reads attributes
off the instance and calls the sync methods from a threadpool. This
module does not import pygeoapi. It adds the async part only, and the
concrete provider pairs the two::

    class PMTilesProvider(AsyncProviderMixin, StorageBackedMixin, BaseMVTProvider):
        native_async = True

The mixin must come FIRST in the bases: pygeoapi's roots never call
``super().__init__``, so placed after them its ``__init__`` would not run
and ``provider_def`` would never be captured.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from functools import cached_property
from typing import Any, ClassVar

from app.provider.storage import ObjectRanges, ObjectStore, load_store, split_source


class AsyncProviderMixin:
    """The async part, and nothing else.

    ``native_async`` is a declaration, never an inspection: a provider
    that awaits its I/O for real sets it to ``True`` and writes the async
    twins (``a`` + the sync method's name: ``aget_tiles``, ``aquery``).
    Everyone else keeps the default and is served through a thread by
    :func:`async_view`.
    """

    native_async: ClassVar[bool] = False

    def __init__(self, provider_def: dict, *args: Any, **kwargs: Any) -> None:
        self.provider_def = provider_def
        # Cooperative by design: the next class in the MRO is the pygeoapi
        # root, which takes `provider_def`. ty only sees `object` here.
        super().__init__(provider_def, *args, **kwargs)  # ty: ignore[too-many-positional-arguments]

    async def run_sync(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking callable in the default executor and await its result."""
        return await asyncio.to_thread(fn, *args, **kwargs)


class AsyncView:
    """An awaitable face over any provider, native or not.

    ``await async_view(p).get_tiles(...)`` resolves to ``p.aget_tiles``
    when ``p`` declares ``native_async`` and has the twin, and to
    ``asyncio.to_thread(p.get_tiles, ...)`` otherwise. Signatures are the
    synchronous ones, one to one. Works on providers that never saw the
    mixin: ``native_async`` is read with a default.
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    @property
    def native(self) -> bool:
        """Whether the provider declared itself natively asynchronous."""
        return bool(getattr(self._provider, "native_async", False))

    def __getattr__(self, name: str) -> Callable[..., Coroutine[Any, Any, Any]]:
        """The coroutine for ``name``: the provider's twin, or its sync method in a thread."""
        if name.startswith("_"):
            raise AttributeError(name)
        if self.native:
            twin = getattr(self._provider, f"a{name}", None)
            if twin is not None:
                return twin
        sync = getattr(self._provider, name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            return await asyncio.to_thread(sync, *args, **kwargs)

        call.__name__ = f"a{name}"
        return call


def async_view(provider: Any) -> AsyncView:
    """The awaitable face of ``provider``; see :class:`AsyncView`."""
    return AsyncView(provider)


class StorageBackedMixin:
    """A store and byte ranges for the provider's ``data`` URL, via the storage layer.

    Reads ``data`` and ``store_options`` from the ``provider_def`` that
    :class:`AsyncProviderMixin` captured: pygeoapi's roots do not keep the
    definition, and ``store_options`` is not one of the attributes they
    set. No provider imports obstore (ADR-0003).
    """

    @cached_property
    def store(self) -> ObjectStore:
        """The object store for the directory or bucket prefix holding ``data``."""
        provider_def = self._captured_provider_def()
        base, _ = split_source(provider_def["data"])
        return load_store(base, provider_def.get("store_options"))

    def byte_ranges(self) -> ObjectRanges:
        """Ranged reads over the ``data`` object itself."""
        return ObjectRanges(self.store, self.object_key)

    @property
    def native_store(self) -> Any:
        """The library-level store object, for libraries that read through obstore themselves.

        async-tiff is the model: it takes an obstore store and the key of
        the object and performs its own ranged reads. When the backend
        exposes no such object the store itself is returned.
        """
        return getattr(self.store, "backend", self.store)

    @property
    def object_key(self) -> str:
        """The key of the ``data`` object within :attr:`store`."""
        _, key = split_source(self._captured_provider_def()["data"])
        return key

    def _captured_provider_def(self) -> dict:
        provider_def = getattr(self, "provider_def", None)
        if provider_def is None:
            raise TypeError(
                f"{type(self).__name__}: provider_def was not captured. Put AsyncProviderMixin "
                "first in the bases, before the pygeoapi root class, which does not call "
                "super().__init__()."
            )
        return provider_def
