"""The mlnative binding against a fake module: missing package or binary, timeout, logs."""

import logging
import sys
from types import SimpleNamespace

import pytest

from tests.maps_fixtures import FakeProcess, tiny_png

SQUARE = (0.0, 0.0, 100_000.0, 100_000.0)  # EPSG:3857 metres
DAY = {"version": 8, "sources": {}, "layers": [{"id": "d", "type": "background"}]}


def _request(bbox=SQUARE, width=64, height=64, style=DAY):
    from app.maps.contract import MapRequest

    return MapRequest(bbox=bbox, width=width, height=height, style=style)


def test_without_mlnative_the_renderer_says_what_to_install(monkeypatch):
    from app.maps.mlnative import create_renderer

    monkeypatch.setitem(sys.modules, "mlnative", None)
    with pytest.raises(ImportError, match="maps dependency group"):
        create_renderer({})


def test_an_mlnative_without_its_binary_is_reported_as_missing(monkeypatch):
    from app.maps.mlnative import create_renderer

    def no_binary():
        raise RuntimeError("Native renderer binary not found")

    monkeypatch.setitem(sys.modules, "mlnative", SimpleNamespace(get_binary_path=no_binary))
    with pytest.raises(ImportError, match="no renderer binary"):
        create_renderer({})


@pytest.mark.asyncio
async def test_the_renderer_builds_its_process_with_mlnative(monkeypatch):
    from app.maps.mlnative import create_renderer
    from app.maps.renderer import ProcessRenderer

    made = []

    class Recording(FakeProcess):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    fake = SimpleNamespace(get_binary_path=lambda: "/bin/true", AsyncRenderer=Recording)
    monkeypatch.setitem(sys.modules, "mlnative", fake)
    renderer = create_renderer({"max_rss_mb": 900})

    assert isinstance(renderer, ProcessRenderer)
    assert await renderer.render(_request()) == tiny_png(64, 64)
    assert renderer.pid == 4242
    # Found once, in the thread that builds the renderer: looking it up stats a file.
    assert made[0].command == ["/bin/true"]
    await renderer.aclose()


@pytest.mark.asyncio
async def test_the_process_waits_a_little_longer_than_the_provider(monkeypatch):
    from app.maps.mlnative import create_renderer

    made = []

    class Recording(FakeProcess):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    fake = SimpleNamespace(get_binary_path=lambda: "/bin/true", AsyncRenderer=Recording)
    monkeypatch.setitem(sys.modules, "mlnative", fake)
    renderer = create_renderer({"timeout": 30, "render_limit": 300})
    await renderer.render(_request())
    await renderer.aclose()

    # Past render_limit the provider replaces the renderer; the process's own
    # timeout must not fire first and turn that into a failure.
    assert made[0].timeout > 300


def test_the_mlnative_loggers_cut_query_strings(monkeypatch):
    from app.maps.mlnative import create_renderer

    fake = SimpleNamespace(get_binary_path=lambda: "/bin/true", AsyncRenderer=FakeProcess)
    monkeypatch.setitem(sys.modules, "mlnative", fake)
    create_renderer({})
    seen = []

    class Keep(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    log = logging.getLogger("mlnative.aio")
    handler = Keep()
    log.addHandler(handler)
    try:
        log.error("load failed: %s", "https://b/a.pmtiles?X-Amz-Signature=SECRET")
    finally:
        log.removeHandler(handler)
    assert seen and "SECRET" not in seen[0]
