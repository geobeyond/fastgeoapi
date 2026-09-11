"""The async part fastgeoapi adds beside pygeoapi's synchronous contract (ADR-0010).

The mixin does not know pygeoapi: the concrete class pairs it with a
root that, like pygeoapi's, never calls ``super().__init__``. Every
import stays at module level on purpose (see tests/test_storage_bridge.py).
"""

import asyncio
import threading

import pytest

from app.provider.base import AsyncProviderMixin, async_view


class _Root:
    """A pygeoapi-like root: takes provider_def, never calls super()."""

    def __init__(self, provider_def):
        self.name = provider_def["name"]

    def get_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        return f"sync:{threading.current_thread().name}:{z}/{x}/{y}".encode()

    def fail(self):
        raise ValueError("boom")


class _Threaded(AsyncProviderMixin, _Root):
    """Not native: served through a thread."""


class _Native(AsyncProviderMixin, _Root):
    native_async = True

    async def aget_tiles(self, layer=None, tileset=None, z=None, y=None, x=None, format_=None):
        return f"async:{threading.current_thread().name}:{z}/{x}/{y}".encode()


class _MixinAfterRoot(_Root, AsyncProviderMixin):
    """The wrong order: the root's __init__ runs and stops there."""


DEF = {"name": "x", "type": "tile", "data": "/nowhere"}


def test_the_mixin_captures_provider_def_and_still_initialises_the_root():
    p = _Threaded(DEF)
    assert p.provider_def is DEF
    assert p.name == "x"
    assert p.native_async is False


def test_after_the_root_the_mixin_never_runs():
    p = _MixinAfterRoot(DEF)
    assert not hasattr(p, "provider_def")


@pytest.mark.asyncio
async def test_a_non_native_provider_is_served_in_another_thread():
    loop_thread = threading.current_thread().name
    out = await async_view(_Threaded(DEF)).get_tiles(z=1, y=2, x=3)
    kind, thread, coords = out.decode().split(":")
    assert (kind, coords) == ("sync", "1/3/2")
    assert thread != loop_thread


@pytest.mark.asyncio
async def test_a_native_provider_is_awaited_on_the_loop_thread():
    loop_thread = threading.current_thread().name
    out = await async_view(_Native(DEF)).get_tiles(z=1, y=2, x=3)
    kind, thread, coords = out.decode().split(":")
    assert (kind, thread, coords) == ("async", loop_thread, "1/3/2")


@pytest.mark.asyncio
async def test_a_twin_is_ignored_unless_native_async_is_declared():
    class Undeclared(AsyncProviderMixin, _Root):
        async def aget_tiles(self, **kwargs):
            raise AssertionError("must not be used: native_async is False")

    out = await async_view(Undeclared(DEF)).get_tiles(z=0, y=0, x=0)
    assert out.startswith(b"sync:")


@pytest.mark.asyncio
async def test_exceptions_and_missing_methods_surface_unchanged():
    view = async_view(_Threaded(DEF))
    with pytest.raises(ValueError, match="boom"):
        await view.fail()
    with pytest.raises(AttributeError):
        view.no_such_method  # ruff: ignore[useless-expression]


def test_the_view_works_on_an_object_that_never_saw_the_mixin():
    view = async_view(_Root(DEF))
    assert view.native is False
    assert asyncio.run(view.get_tiles(z=0, y=0, x=0)).startswith(b"sync:")


@pytest.mark.asyncio
async def test_run_sync_awaits_a_blocking_callable_off_the_loop():
    p = _Threaded(DEF)
    assert await p.run_sync(threading.current_thread) is not threading.current_thread()
