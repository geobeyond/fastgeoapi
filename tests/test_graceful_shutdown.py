"""Stopping the server while a pygeoapi call still runs in its thread.

``app.*`` is imported at the top of this module, nowhere else.
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pygeoapi.util import yaml_load
from starlette.requests import Request

from app import cli
from app.provider.duckdb_ import connect
from app.provider.geoparquet import GeoParquetProvider
from app.pygeoapi.factory import build_api, build_openapi, execute

LAKES = str(Path(__file__).parent / "data" / "lakes.parquet")
# Ten billion rows: the query runs until something stops it.
ENDLESS = "SELECT count(*) FROM range(10000000000) t(i) WHERE running(i) % 7 = 3"


def _run_options(runner, monkeypatch, *args: str) -> dict:
    seen: dict = {}
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: seen.update(k))
    result = runner.invoke(cli.app, ["run", *args])
    assert result.exit_code == 0, result.output
    return seen


def test_a_ctrl_c_waits_ten_seconds_at_most_for_the_running_requests(runner, monkeypatch):
    assert _run_options(runner, monkeypatch)["timeout_graceful_shutdown"] == 10


def test_the_wait_is_an_option(runner, monkeypatch):
    options = _run_options(runner, monkeypatch, "--graceful-timeout", "3")

    assert options["timeout_graceful_shutdown"] == 3


@pytest.fixture(scope="module")
def api():
    config = yaml_load(Path("tests/data/pygeoapi-config.yml").open())
    return build_api(config, build_openapi(config))


def _request() -> Request:
    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
    return Request(scope, receive)


class _Work:
    """What a call does in its thread, and the connections its queries run on."""

    def __init__(self) -> None:
        self.running = threading.Event()
        self.opened: list = []

    def endless(self, con) -> None:
        """Run ENDLESS on ``con``; ``running`` is set once the query has started."""

        def mark(i: int) -> int:
            self.running.set()
            return i

        self.opened.append(con)
        con.create_function("running", mark)
        con.execute(ENDLESS).fetchall()


def _provider() -> GeoParquetProvider:
    return GeoParquetProvider(
        {
            "name": "GeoParquet",
            "type": "feature",
            "data": LAKES,
            "id_field": "id",
            "geometry_column": "geometry",
        }
    )


async def _wait(event: threading.Event, request=None, seconds: float = 10.0) -> bool:
    """Wait for ``event``, or for ``request`` to end, without taking a thread from the executor."""
    deadline = time.monotonic() + seconds
    while not event.is_set() and not (request and request.done()) and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    return event.is_set()


async def _cancel_while_running(api, work, after_cancel=lambda: None) -> dict:
    """Cancel the request once ``work`` runs, and say how ``work`` ended.

    ``work`` gets a ``_Work`` and sets its ``running`` event. ``after_cancel``
    runs once the request is cancelled.
    """
    state = _Work()
    ended = threading.Event()
    outcome: dict = {}

    def call(api, api_request):
        try:
            work(state)
        except Exception as error:
            outcome["error"] = type(error).__name__
        finally:
            ended.set()
        return {"Content-Type": "application/json"}, 200, "{}"

    request = asyncio.ensure_future(execute(api, call, _request(), skip_valid_check=True))
    started = await _wait(state.running, request)
    if request.done():
        request.result()  # The request failed before the call ran: say why.
    assert started, "the call never started"
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    after_cancel()
    stopped = await _wait(ended)
    if not stopped:
        # Closing the loop waits for its threads: stop the query here, or the run hangs.
        for con in state.opened:
            con.interrupt()
        await _wait(ended)
    assert stopped, "the work went on after the request was cancelled"
    return outcome


@pytest.mark.asyncio
async def test_cancelling_the_request_interrupts_the_query_of_its_connection(api):
    outcome = await _cancel_while_running(api, lambda work: work.endless(connect(LAKES)))

    assert outcome == {"error": "InterruptException"}


@pytest.mark.asyncio
async def test_cancelling_the_request_interrupts_the_query_of_a_provider_cursor(api):
    outcome = await _cancel_while_running(api, lambda work: work.endless(_provider()._cursor()))

    assert outcome == {"error": "InterruptException"}


@pytest.mark.asyncio
async def test_a_cancelled_request_cannot_start_another_query(api):
    resume = threading.Event()

    def start_late(work: _Work) -> None:
        provider = _provider()
        work.running.set()
        resume.wait(10)
        work.endless(provider._cursor())

    outcome = await _cancel_while_running(api, start_late, after_cancel=resume.set)

    assert outcome == {"error": "CallInterruptedError"}


@pytest.mark.asyncio
async def test_the_thread_of_a_cancelled_request_serves_the_next_job(api):
    loop = asyncio.get_running_loop()
    one_thread = ThreadPoolExecutor(max_workers=1)
    loop.set_default_executor(one_thread)
    try:
        await _cancel_while_running(api, lambda work: work.endless(connect(LAKES)))

        con = await loop.run_in_executor(None, connect, LAKES)
        rows = await loop.run_in_executor(None, lambda: con.execute("SELECT 1").fetchall())
    finally:
        one_thread.shutdown(wait=False)

    assert rows == [(1,)]
