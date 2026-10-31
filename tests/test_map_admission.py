"""The admission of maps in the route: how many draw, how many wait, and for how long.

``app.*`` is imported at the top of this module, nowhere else.
"""

import asyncio

import pytest

from app.interfaces.providers import MapLimits
from app.provider.maps import MapRendererBusyError, MapRenderTimeoutError
from app.pygeoapi.api_async.admission import MapAdmission, admission_for


class _Gate:
    """Draws that wait for one event, and count how many have started."""

    def __init__(self):
        self.event = asyncio.Event()
        self.started = 0

    async def draw(self) -> bytes:
        self.started += 1
        await self.event.wait()
        return b"png"


async def _until(condition, timeout=2.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "the admission never reached the expected state"
        await asyncio.sleep(0.005)


@pytest.mark.asyncio
async def test_a_full_admission_refuses_with_retry_after():
    admission = MapAdmission(concurrent=1, waiting=1, timeout=5.0)
    gate = _Gate()
    drawing = asyncio.create_task(admission.run(gate.draw))
    waiting = asyncio.create_task(admission.run(gate.draw))
    await _until(lambda: admission.occupied == 2)

    with pytest.raises(MapRendererBusyError) as error:
        await admission.run(gate.draw)
    assert error.value.retry_after == 5
    gate.event.set()
    assert await asyncio.gather(drawing, waiting) == [b"png", b"png"]


@pytest.mark.asyncio
async def test_two_concurrent_slots_draw_two_maps_at_once():
    admission = MapAdmission(concurrent=2, waiting=0, timeout=5.0)
    gate = _Gate()
    maps = [asyncio.create_task(admission.run(gate.draw)) for _ in range(2)]

    await _until(lambda: gate.started == 2)
    gate.event.set()
    await asyncio.gather(*maps)


@pytest.mark.asyncio
async def test_a_cancelled_wait_gives_its_place_back():
    admission = MapAdmission(concurrent=1, waiting=1, timeout=5.0)
    gate = _Gate()
    drawing = asyncio.create_task(admission.run(gate.draw))
    waiting = asyncio.create_task(admission.run(gate.draw))
    await _until(lambda: admission.occupied == 2)

    waiting.cancel()
    await _until(lambda: admission.occupied == 1)
    assert gate.started == 1
    gate.event.set()
    await drawing


@pytest.mark.asyncio
async def test_a_slow_map_times_out_and_keeps_its_slot_until_it_ends():
    admission = MapAdmission(concurrent=1, waiting=0, timeout=0.05)
    gate = _Gate()

    with pytest.raises(MapRenderTimeoutError):
        await admission.run(gate.draw)
    assert admission.occupied == 1
    gate.event.set()
    await _until(lambda: admission.occupied == 0)


@pytest.mark.asyncio
async def test_a_wait_past_the_timeout_answers_in_time():
    admission = MapAdmission(concurrent=1, waiting=1, timeout=0.05)
    gate = _Gate()
    with pytest.raises(MapRenderTimeoutError):
        await admission.run(gate.draw)

    loop = asyncio.get_running_loop()
    started = loop.time()
    with pytest.raises(MapRenderTimeoutError):
        await admission.run(gate.draw)
    assert loop.time() - started < 1
    assert gate.started == 1
    gate.event.set()


@pytest.mark.asyncio
async def test_each_provider_instance_has_its_own_admission():
    class Provider:
        pass

    limits = MapLimits(64, 64, None, 1, 1, 5.0)
    old, new = Provider(), Provider()
    gate = _Gate()
    drawing = asyncio.create_task(admission_for(old, limits).run(gate.draw))
    await _until(lambda: admission_for(old, limits).occupied == 1)

    assert admission_for(old, limits) is admission_for(old, limits)
    assert admission_for(new, limits).occupied == 0
    gate.event.set()
    await drawing
