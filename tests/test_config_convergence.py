"""Every worker converges to the configuration source (issue #455).

The configuration reload is per process: with `uvicorn --workers N` the
webhook reaches one worker and the others keep serving the previous
revision. Nothing new propagates anything here — each process simply
asks `ReloadManager.trigger()` every few seconds, and the ETag comparison
it already performs decides whether there is work.

Two things the manager has to say for a control plane to read the
convergence, both behind the authenticated status endpoint and neither
on the public probes, which are unauthenticated by design and should not
carry a content hash or a process count: which process is answering, and
which revision that process is **serving** — as opposed to what its last
attempt saw.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest

from app.interfaces.reload import ConfigPoller, ReloadManager
from app.pygeoapi.holder import PygeoapiHolder


async def _asgi(scope, receive, send) -> None:
    """A stand-in sub-app: `PygeoapiHolder.swap` expects a callable."""


class TestStatusNamesTheProcess:
    def test_the_instance_is_an_opaque_eight_hex_identifier(self):
        """Not the PID: opaque, not enumerable, says nothing about the host."""
        manager = ReloadManager(PygeoapiHolder(), source="unused")

        assert re.fullmatch(r"[0-9a-f]{8}", manager.status()["instance"])

    def test_the_instance_is_stable_within_the_process(self):
        one = ReloadManager(PygeoapiHolder(), source="unused")
        two = ReloadManager(PygeoapiHolder(), source="unused")

        assert one.status()["instance"] == two.status()["instance"]
        assert one.status()["instance"] == one.status()["instance"]

    def test_the_etag_is_the_revision_in_service(self):
        holder = PygeoapiHolder()
        holder.swap(_asgi, etag='"served"')
        manager = ReloadManager(holder, source="unused")

        assert manager.status()["etag"] == '"served"'

    def test_a_failed_attempt_does_not_change_what_is_served(self):
        """`last` says what the last attempt saw; `etag` says what serves.

        A worker whose last reload failed still serves the previous
        revision, and a control plane waiting for convergence has to be
        told that rather than read the failure as progress.
        """
        holder = PygeoapiHolder()
        holder.swap(_asgi, etag='"previous"')
        manager = ReloadManager(holder, source="unused")
        manager._record("failed", error="boom", etag='"attempted"')

        status = manager.status()

        assert status["last"]["outcome"] == "failed"
        assert status["etag"] == '"previous"'


class _Trigger:
    """A stand-in for `ReloadManager.trigger`, counting and failing on cue."""

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls = 0
        self.fail_on = fail_on

    async def __call__(self) -> dict:
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("the bucket blinked")
        return {"status": "started"}


class TestSetting:
    """`FASTGEOAPI_CONFIG_POLL_SECONDS`: 0 is off, N is the interval."""

    def test_off_by_default(self):
        """One worker needs no poll: the webhook reaches it, and a HEAD
        every few seconds with nothing to learn is noise."""
        from unittest import mock

        from app.config.app import DevConfig

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEV_FASTGEOAPI_CONFIG_POLL_SECONDS", None)
            assert DevConfig().FASTGEOAPI_CONFIG_POLL_SECONDS == 0

    def test_the_environment_sets_the_interval(self):
        from unittest import mock

        from app.config.app import DevConfig

        with mock.patch.dict(os.environ, {"DEV_FASTGEOAPI_CONFIG_POLL_SECONDS": "3"}):
            assert DevConfig().FASTGEOAPI_CONFIG_POLL_SECONDS == 3


class TestLifespan:
    """The poller is one task per process, born and buried with the app."""

    def _env(self, tmp_path, poll: str) -> dict[str, str]:
        import yaml

        from tests.test_config_reload import BASE_ENV, _write_config

        target = tmp_path / "pygeoapi-config.yml"
        _write_config(target, yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text()))
        return {
            **BASE_ENV,
            "DEV_PYGEOAPI_CONFIG": str(target),
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_FASTGEOAPI_CONFIG_POLL_SECONDS": poll,
        }

    def test_a_positive_interval_starts_a_poller_and_shutdown_stops_it(self, tmp_path):
        from unittest import mock

        from starlette.testclient import TestClient

        from tests.test_config_reload import _reload_app

        with mock.patch.dict(os.environ, self._env(tmp_path, "1"), clear=False):
            app = _reload_app(os.environ)
            with TestClient(app):
                task = app.state.config_poller
                assert isinstance(task, asyncio.Task)
                assert not task.done()
            assert task.cancelled() or task.done()

    def test_zero_starts_nothing(self, tmp_path):
        from unittest import mock

        from starlette.testclient import TestClient

        from tests.test_config_reload import _reload_app

        with mock.patch.dict(os.environ, self._env(tmp_path, "0"), clear=False):
            app = _reload_app(os.environ)
            with TestClient(app):
                assert getattr(app.state, "config_poller", None) is None


class TestCli:
    """`fastgeoapi run --workers N`, N > 1, turns the poll on by itself.

    The flag stays — removing a capability to prevent a footgun is the
    right call only when the footgun has no remedy, and this one costs a
    HEAD every five seconds. Using it simply stops being silently broken.
    """

    def _run(self, runner, monkeypatch, args: list[str]) -> None:
        import app.cli as cli_module

        monkeypatch.setattr(cli_module.uvicorn, "run", lambda *a, **k: None)
        result = runner.invoke(cli_module.app, ["run", *args])
        assert result.exit_code == 0, result.output

    def test_more_than_one_worker_enables_the_poll(self, runner, monkeypatch):
        monkeypatch.setenv("ENV_STATE", "dev")
        monkeypatch.delenv("DEV_FASTGEOAPI_CONFIG_POLL_SECONDS", raising=False)

        self._run(runner, monkeypatch, ["--workers", "2"])

        assert os.environ["DEV_FASTGEOAPI_CONFIG_POLL_SECONDS"] == "5"

    def test_one_worker_leaves_it_alone(self, runner, monkeypatch):
        monkeypatch.setenv("ENV_STATE", "dev")
        monkeypatch.delenv("DEV_FASTGEOAPI_CONFIG_POLL_SECONDS", raising=False)

        self._run(runner, monkeypatch, ["--workers", "1"])

        assert "DEV_FASTGEOAPI_CONFIG_POLL_SECONDS" not in os.environ

    def test_an_explicit_interval_is_respected(self, runner, monkeypatch):
        monkeypatch.setenv("ENV_STATE", "dev")
        monkeypatch.setenv("DEV_FASTGEOAPI_CONFIG_POLL_SECONDS", "30")

        self._run(runner, monkeypatch, ["--workers", "4"])

        assert os.environ["DEV_FASTGEOAPI_CONFIG_POLL_SECONDS"] == "30"


class TestPoller:
    @pytest.mark.asyncio
    async def test_it_asks_for_a_reload_at_every_interval(self):
        trigger = _Trigger()
        poller = ConfigPoller(trigger, interval=0.01)

        task = asyncio.create_task(poller.run())
        await asyncio.sleep(0.12)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert trigger.calls >= 5

    @pytest.mark.asyncio
    async def test_a_failing_attempt_does_not_stop_it(self):
        """A source that blinks produces a log line, not a dead worker."""
        trigger = _Trigger(fail_on=2)
        poller = ConfigPoller(trigger, interval=0.01)

        task = asyncio.create_task(poller.run())
        await asyncio.sleep(0.12)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert trigger.calls >= 5

    @pytest.mark.asyncio
    async def test_cancelling_stops_it_promptly(self):
        trigger = _Trigger()
        poller = ConfigPoller(trigger, interval=60)

        task = asyncio.create_task(poller.run())
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert trigger.calls == 1
