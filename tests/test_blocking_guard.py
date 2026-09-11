"""No blocking call reaches the event loop: an assertion, not a promise (ADR-0010, decision 8)."""

import asyncio
import time

import pytest
from blockbuster import BlockingError, blockbuster_ctx

from app.provider.base import AsyncProviderMixin, async_view


class _Root:
    def __init__(self, provider_def):
        self.name = provider_def["name"]


class _Sleepy(AsyncProviderMixin, _Root):
    """Declares itself native, then blocks the loop: exactly what the guard is for."""

    native_async = True

    async def aget_tiles(self, **kwargs):
        time.sleep(0.001)
        return b""


class _Honest(AsyncProviderMixin, _Root):
    native_async = True

    async def aget_tiles(self, **kwargs):
        await asyncio.sleep(0)
        return b"ok"


class _Threaded(AsyncProviderMixin, _Root):
    def get_tiles(self, **kwargs):
        time.sleep(0.001)
        return b"slow but off the loop"


@pytest.mark.asyncio
async def test_a_native_provider_that_blocks_the_loop_is_caught():
    with blockbuster_ctx(), pytest.raises(BlockingError):
        await async_view(_Sleepy({"name": "s"})).get_tiles()


@pytest.mark.asyncio
async def test_an_honest_native_provider_passes():
    with blockbuster_ctx():
        assert await async_view(_Honest({"name": "h"})).get_tiles() == b"ok"


@pytest.mark.asyncio
async def test_the_threadpool_fallback_may_block_because_it_is_not_on_the_loop():
    with blockbuster_ctx():
        assert await async_view(_Threaded({"name": "t"})).get_tiles() == b"slow but off the loop"
