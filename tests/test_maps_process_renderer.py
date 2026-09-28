"""The process renderer with a fake process: sizes, styles, memory and failures."""

import io
import json

import pytest
from PIL import Image

from tests.maps_fixtures import FakeProcess, tiny_png

SQUARE = (0.0, 0.0, 100_000.0, 100_000.0)  # EPSG:3857 metres
WIDE = (0.0, 0.0, 300_000.0, 100_000.0)
DAY = {"version": 8, "sources": {}, "layers": [{"id": "d", "type": "background"}]}
NIGHT = {"version": 8, "sources": {}, "layers": [{"id": "n", "type": "background"}]}


def _renderer(processes, **kwargs):
    from app.maps.renderer import ProcessRenderer

    def factory(width, height, style):
        process = FakeProcess(width, height, style)
        processes.append(process)
        return process

    kwargs.setdefault("rss", lambda pid: None)
    return ProcessRenderer(process=factory, **kwargs)


def _request(bbox=SQUARE, width=64, height=64, style=DAY):
    from app.maps.contract import MapRequest

    return MapRequest(bbox=bbox, width=width, height=height, style=style)


def _renders(process):
    return [call for call in process.calls if call[0] == "render"]


def test_the_process_renderer_meets_the_renderer_contract():
    from app.maps.contract import MapRenderer

    assert isinstance(_renderer([]), MapRenderer)


@pytest.mark.asyncio
async def test_a_map_with_the_image_aspect_passes_the_renderer_png_through():
    processes = []
    png = await _renderer(processes).render(_request())

    (process,) = processes
    assert process.calls == [("start",), ("render", (64, 64), "png")]
    assert png == tiny_png(64, 64)


@pytest.mark.asyncio
async def test_another_aspect_is_drawn_smaller_and_stretched_to_the_image():
    processes = []
    png = await _renderer(processes).render(_request(bbox=WIDE, width=90, height=90))

    assert _renders(processes[0]) == [("render", (90, 30), "rgba")]
    assert Image.open(io.BytesIO(png)).size == (90, 90)


@pytest.mark.asyncio
async def test_the_process_starts_once_and_is_resized_for_each_map():
    processes = []
    renderer = _renderer(processes)
    await renderer.render(_request(width=64, height=64))
    await renderer.render(_request(width=256, height=256))

    assert len(processes) == 1
    assert processes[0].created_with[:2] == (64, 64)
    assert _renders(processes[0]) == [("render", (64, 64), "png"), ("render", (256, 256), "png")]


@pytest.mark.asyncio
async def test_the_style_is_sent_again_only_when_it_changes():
    processes = []
    renderer = _renderer(processes)
    for style in (DAY, DAY, NIGHT):
        await renderer.render(_request(style=style))

    calls = processes[0].calls
    assert [call[0] for call in calls] == ["start", "render", "render", "reload", "render"]
    assert json.loads(calls[3][1]) == NIGHT
    assert json.loads(processes[0].created_with[2]) == DAY


@pytest.mark.asyncio
async def test_a_process_above_max_rss_is_replaced_after_the_map():
    processes = []
    renderer = _renderer(processes, max_rss_mb=600, rss=lambda pid: 700.0)
    await renderer.render(_request())

    assert processes[0].closed and renderer.pid is None
    await renderer.render(_request())
    assert len(processes) == 2


@pytest.mark.asyncio
async def test_without_a_memory_reading_the_process_is_kept():
    processes = []
    renderer = _renderer(processes, rss=lambda pid: None)
    await renderer.render(_request())

    assert not processes[0].closed and renderer.pid == 4242


@pytest.mark.asyncio
async def test_a_failure_replaces_the_process_and_keeps_the_url_out_of_the_error():
    from app.maps.contract import RenderError

    processes = []
    renderer = _renderer(processes)
    await renderer.render(_request())
    processes[0].fail = OSError(
        "could not load pmtiles://https://b/a.pmtiles?X-Amz-Signature=SECRET"
    )

    with pytest.raises(RenderError) as error:
        await renderer.render(_request())
    assert "SECRET" not in str(error.value)
    assert processes[0].closed

    await renderer.render(_request())
    assert len(processes) == 2


@pytest.mark.asyncio
async def test_a_dead_process_is_replaced_at_the_next_map():
    from app.maps.contract import RenderError

    processes = []
    renderer = _renderer(processes)
    await renderer.render(_request())
    processes[0].fail = RuntimeError("Renderer is not running")

    with pytest.raises(RenderError):
        await renderer.render(_request())
    png = await renderer.render(_request())

    assert len(processes) == 2 and png == tiny_png(64, 64)


@pytest.mark.asyncio
async def test_aclose_stops_the_process():
    processes = []
    renderer = _renderer(processes)
    await renderer.render(_request())
    await renderer.aclose()

    assert processes[0].closed and renderer.pid is None


def test_redact_cuts_query_strings():
    from app.maps.renderer import redact

    text = "GET https://b.example/a.pmtiles?X-Amz-Signature=SECRET&x=1 failed"
    assert redact(text) == "GET https://b.example/a.pmtiles?<redacted> failed"
