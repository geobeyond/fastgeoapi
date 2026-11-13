"""The render queue: one renderer, built at the first map, and the maps that wait for it."""

import asyncio

import pytest

from tests.maps_fixtures import FakeRenderer, create_fake_renderer, tiny_png


@pytest.fixture(autouse=True)
def _fresh_fakes():
    FakeRenderer.instances.clear()
    FakeRenderer.gate = None
    yield
    FakeRenderer.instances.clear()


def _queue(fake="ok", **limits):
    from app.maps.queue import RenderQueue

    limits = {"size": 8, "timeout": 5.0, "render_limit": 20.0, **limits}
    return RenderQueue(lambda: create_fake_renderer({"fake": fake}), **limits)


def _request():
    from app.maps.contract import MapRequest

    return MapRequest(bbox=(0.0, 0.0, 1000.0, 1000.0), width=16, height=16, style={})


async def _until(condition, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "the queue never reached the expected state"
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_the_renderer_is_built_at_the_first_map_only():
    queue = _queue()

    assert not queue.renderer_is_built
    assert await queue.draw(_request()) == tiny_png(16, 16)
    await queue.draw(_request())
    assert len(FakeRenderer.instances) == 1 and queue.renderer_is_built


@pytest.mark.asyncio
async def test_a_full_queue_refuses_the_next_map():
    from app.maps.queue import QueueFullError

    FakeRenderer.gate = asyncio.Event()
    queue = _queue("gate", size=1)
    drawing = asyncio.create_task(queue.draw(_request()))
    waiting = asyncio.create_task(queue.draw(_request()))
    await _until(lambda: queue.waiting == 2)

    with pytest.raises(QueueFullError):
        await queue.draw(_request())
    FakeRenderer.gate.set()
    await asyncio.gather(drawing, waiting)


@pytest.mark.asyncio
async def test_a_cancelled_wait_gives_its_place_back():
    FakeRenderer.gate = asyncio.Event()
    queue = _queue("gate", size=1)
    drawing = asyncio.create_task(queue.draw(_request()))
    waiting = asyncio.create_task(queue.draw(_request()))
    await _until(lambda: queue.waiting == 2)

    waiting.cancel()
    await _until(lambda: queue.waiting == 1)
    FakeRenderer.gate.set()
    await drawing


@pytest.mark.asyncio
async def test_a_slow_map_times_out_and_its_render_goes_on():
    from app.maps.queue import DrawTimeoutError

    FakeRenderer.gate = asyncio.Event()
    queue = _queue("gate", timeout=0.05, render_limit=5.0)

    with pytest.raises(DrawTimeoutError):
        await queue.draw(_request())
    (renderer,) = FakeRenderer.instances
    FakeRenderer.gate.set()
    await _until(lambda: len(renderer.requests) == 1 and queue.waiting == 0)
    assert not renderer.closed and queue.renderer_is_built


@pytest.mark.asyncio
async def test_a_render_past_its_limit_replaces_the_renderer():
    from app.maps.queue import DrawTimeoutError

    queue = _queue("slow", timeout=1.0, render_limit=0.1)

    with pytest.raises(DrawTimeoutError):
        await queue.draw(_request())
    await _until(lambda: FakeRenderer.instances[0].closed)
    assert not queue.renderer_is_built


@pytest.mark.asyncio
async def test_a_failing_renderer_is_replaced_and_its_error_kept_private():
    from app.maps.contract import RenderError

    queue = _queue("oserror-once")

    with pytest.raises(RenderError) as error:
        await queue.draw(_request())
    assert "SECRET" not in str(error.value)
    await queue.draw(_request())
    assert len(FakeRenderer.instances) == 2


@pytest.mark.asyncio
async def test_aclose_waits_for_the_renderer_to_close():
    queue = _queue()
    await queue.draw(_request())

    await queue.aclose()
    assert FakeRenderer.instances[0].closed and not queue.renderer_is_built
