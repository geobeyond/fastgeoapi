"""Every worker converges to the configuration source.

The configuration reload is per process. With `uvicorn --workers N` the
webhook reaches one worker and the others keep serving the previous
revision. Each process asks `ReloadManager.trigger()` every few seconds,
and the ETag comparison it already performs decides whether there is
work to do.

For a control plane to observe the convergence, the manager reports two
things: which process is answering, and which revision that process is
serving, which can differ from what its last attempt saw. The
authenticated status endpoint exposes both. The public probes do not:
they are unauthenticated by design and should not carry a content hash
or a process identifier.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path

import pytest

from app.interfaces.reload import ReloadManager
from app.pygeoapi.holder import PygeoapiHolder


async def _asgi(scope, receive, send) -> None:
    """A stand-in sub-app: `PygeoapiHolder.swap` expects a callable."""


def _manager(holder: PygeoapiHolder | None = None) -> ReloadManager:
    return ReloadManager(
        holder or PygeoapiHolder(), source="unused", instance="0badf00d"
    )


class TestStatusNamesTheProcess:
    def test_the_instance_is_the_one_the_application_gave_it(self):
        """The manager reports the identity the application gave it.

        The application generates it once per process; a control plane
        reads it to tell workers apart.
        """
        assert _manager().status()["instance"] == "0badf00d"

    def test_the_etag_is_the_revision_in_service(self):
        holder = PygeoapiHolder()
        holder.swap(_asgi, etag='"served"')

        assert _manager(holder).status()["etag"] == '"served"'

    def test_a_failed_attempt_does_not_change_what_is_served(self):
        """`last` describes the last attempt; `etag` describes what serves.

        A worker whose last reload failed still serves the previous
        revision, and a control plane waiting for convergence needs to
        see that.
        """
        holder = PygeoapiHolder()
        holder.swap(_asgi, etag='"previous"')
        manager = _manager(holder)
        manager._record("failed", error="boom")

        status = manager.status()

        assert status["last"]["outcome"] == "failed"
        assert "etag" not in status["last"]
        assert status["etag"] == '"previous"'


class _Trigger:
    """A stand-in for `ReloadManager.trigger`.

    Counts the calls and raises on the call number given as `fail_on`.
    """

    def __init__(self, fail_on: int | None = None) -> None:
        self.calls = 0
        self.fail_on = fail_on

    async def __call__(self) -> dict:
        self.calls += 1
        if self.calls == self.fail_on:
            raise RuntimeError("the bucket is unreachable")
        return {"status": "started"}


class TestSetting:
    """`FASTGEOAPI_CONFIG_POLL_SECONDS`: 0 is off, N is the interval."""

    def test_off_by_default(self):
        """With one worker the webhook already reaches the only process,
        and polling would add a HEAD every few seconds for nothing."""
        from unittest import mock

        from app.config.app import DevConfig

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DEV_FASTGEOAPI_CONFIG_POLL_SECONDS", None)
            assert DevConfig().FASTGEOAPI_CONFIG_POLL_SECONDS == 0

    def test_the_environment_sets_the_interval(self):
        from unittest import mock

        from app.config.app import DevConfig

        with mock.patch.dict(
            os.environ, {"DEV_FASTGEOAPI_CONFIG_POLL_SECONDS": "3"}
        ):
            assert DevConfig().FASTGEOAPI_CONFIG_POLL_SECONDS == 3


class TestLifespan:
    """One poller task per process, started and cancelled with the app."""

    def _env(self, tmp_path, poll: str) -> dict[str, str]:
        import yaml

        from tests.test_config_reload import BASE_ENV, _write_config

        target = tmp_path / "pygeoapi-config.yml"
        _write_config(
            target,
            yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text()),
        )
        return {
            **BASE_ENV,
            "DEV_PYGEOAPI_CONFIG": str(target),
            "DEV_API_KEY_ENABLED": "false",
            "DEV_JWKS_ENABLED": "false",
            "DEV_FASTGEOAPI_CONFIG_POLL_SECONDS": poll,
        }

    def test_a_positive_interval_starts_a_poller_and_shutdown_stops_it(
        self, tmp_path
    ):
        from unittest import mock

        from starlette.testclient import TestClient

        from tests.test_config_reload import _reload_app

        with mock.patch.dict(os.environ, self._env(tmp_path, "1"), clear=False):
            app = _reload_app(os.environ)
            with TestClient(app) as client:
                task = app.state.config_poller
                assert isinstance(task, asyncio.Task)
                assert not task.done()
                # Eight hex characters of a random token; a PID would not match.
                instance = client.get("/admin/config/reload").json()["instance"]
                assert re.fullmatch(r"[0-9a-f]{8}", instance)
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

    Removing the flag was the alternative considered. Keeping it
    costs a HEAD every five seconds per worker, and the reload keeps
    working.
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
    def _polling(self, trigger: _Trigger, interval: float):
        from unittest import mock

        manager = _manager()
        patched = mock.patch.object(manager, "trigger", trigger)
        patched.start()
        task = asyncio.create_task(manager.poll_forever(interval))
        return task, patched

    @pytest.mark.asyncio
    async def test_it_asks_for_a_reload_at_every_interval(self):
        trigger = _Trigger()
        task, patched = self._polling(trigger, interval=0.01)
        await asyncio.sleep(0.12)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        patched.stop()

        assert trigger.calls >= 5

    @pytest.mark.asyncio
    async def test_a_failing_attempt_does_not_stop_it(self):
        """A transient error on the source is logged and the loop keeps going."""
        trigger = _Trigger(fail_on=2)
        task, patched = self._polling(trigger, interval=0.01)
        await asyncio.sleep(0.12)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        patched.stop()

        assert trigger.calls >= 5

    @pytest.mark.asyncio
    async def test_cancelling_stops_it_promptly(self):
        trigger = _Trigger()
        task, patched = self._polling(trigger, interval=60)
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        patched.stop()

        assert trigger.calls == 1
