"""Two real uvicorn workers reading one configuration source.

Everything else in the suite runs the app in process, where there is one
copy of the configuration by construction. The other case: `uvicorn --workers 2`
gives every worker its own memory, the reload webhook reaches whichever
process accepts the connection, and the other keeps serving the previous
revision. Seeing that takes two processes, so this file starts them.

The opaque ``instance`` reported by the authenticated status endpoint
tells the workers apart, and ``etag`` says which revision each one
serves. Sampling goes through the socket uvicorn shares between the
workers, and the kernel decides which worker accepts each connection.
"We saw two instances" is therefore a lower bound on the worker count,
and both tests say so where they rely on it.
"""

from __future__ import annotations

import asyncio
import copy
import os
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import yaml

from tests.test_config_reload import BASE_ENV

REPO = Path(__file__).resolve().parents[1]
STATUS = "/admin/config/reload"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _etag_of(path: Path) -> str:
    from app.config.source import astat_config_source

    etag = asyncio.run(astat_config_source(str(path))).etag
    assert etag is not None, (
        "a local file always carries an ETag (inode-mtime-size)"
    )
    return etag


@contextmanager
def _serve(
    tmp_path: Path, poll_seconds: str, workers: int = 2
) -> Iterator[tuple[str, Path]]:
    """Start uvicorn with `workers` processes on a configuration file on disk."""
    config_path = tmp_path / "pygeoapi-config.yml"
    config_path.write_text(
        Path(REPO, "tests/data/pygeoapi-config.yml").read_text()
    )
    port = _free_port()
    env = {
        **os.environ,
        **BASE_ENV,
        "DEV_PYGEOAPI_CONFIG": str(config_path),
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_FASTGEOAPI_CONFIG_POLL_SECONDS": poll_seconds,
    }
    log = (tmp_path / "server.log").open("w")
    # Our own interpreter and our own module; no untrusted input.
    server = subprocess.Popen(  # ruff: ignore[subprocess-without-shell-equals-true]
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            str(workers),
        ],
        cwd=REPO,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_ready(base, server, tmp_path / "server.log")
        yield base, config_path
    finally:
        server.terminate()
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()


def _wait_ready(
    base: str, server: subprocess.Popen, log: Path, timeout: float = 90.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise AssertionError(
                f"the server exited early:\n{log.read_text()[-3000:]}"
            )
        try:
            if httpx.get(f"{base}/readyz", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise AssertionError(
        f"the server was not ready within {timeout}s:\n{log.read_text()[-3000:]}"
    )


def _sample(base: str, rounds: int = 32) -> dict[str, str]:
    """`instance -> etag` for as many workers as answered a burst.

    The requests go out concurrently, one connection each, closed after
    the response. Sequential requests are not enough: on Linux the kernel
    tends to wake the same worker for one connection at a time, and in CI
    thirty requests in a row all landed on a single process. A burst
    leaves several connections pending at once, so both workers get to
    drain the accept queue.
    """

    def one(_: int) -> tuple[str, str]:
        body = httpx.get(
            f"{base}{STATUS}", headers={"Connection": "close"}, timeout=5
        ).json()
        return body["instance"], body["etag"]

    with ThreadPoolExecutor(max_workers=rounds) as pool:
        return dict(pool.map(one, range(rounds)))


def _sample_two(base: str, timeout: float = 30.0) -> dict[str, str]:
    """Sample until two workers have answered, or skip with the reason.

    Through one shared socket the instances seen are a lower bound on the
    worker count. If burst after burst reaches a single process, nothing
    about convergence can be observed here, and the test is skipped with
    that reason.
    """
    deadline = time.monotonic() + timeout
    seen: dict[str, str] = {}
    while time.monotonic() < deadline:
        seen = _sample(base)
        if len(seen) >= 2:
            return seen
        time.sleep(0.2)
    pytest.skip(f"the sampling reached a single worker in {timeout}s: {seen}")


def _add_a_collection(config_path: Path) -> str:
    config = yaml.safe_load(config_path.read_text())
    config["resources"]["lakes-bis"] = copy.deepcopy(
        config["resources"]["lakes"]
    )
    config["resources"]["lakes-bis"]["title"] = {"en": "Lakes bis"}
    config_path.write_text(yaml.safe_dump(config))
    return _etag_of(config_path)


def test_the_defect_the_issue_describes(tmp_path):
    """With the poll off, the webhook updates one worker and not the other.

    This reproduces that behavior. It also guards the next test: if the workers
    agreed here, the convergence test would prove nothing.
    """
    with _serve(tmp_path, poll_seconds="0") as (base, config_path):
        before = _sample_two(base)
        (old_etag,) = set(before.values())

        new_etag = _add_a_collection(config_path)
        assert new_etag != old_etag

        assert httpx.post(f"{base}{STATUS}", timeout=10).status_code == 202
        # Give the one worker that took the POST time to rebuild.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            after = _sample(base)
            if new_etag in after.values():
                break
            time.sleep(0.5)
        else:
            raise AssertionError(
                f"no worker ever served the new revision: {after}"
            )

        assert len(after) >= 2, (
            f"only one worker answered after the reload: {after}"
        )
        assert set(after.values()) == {old_etag, new_etag}, (
            f"expected one worker reloaded and one not, but they report {after}"
        )


def test_every_worker_converges_to_the_source(tmp_path):
    """With the poll on, a new revision reaches every worker without a POST.

    The file changes and, within the interval plus a margin, every
    instance that answers serves the new ETag. The sampling only covers
    the instances that answer, so the test requires at least two before
    asserting anything about more than one process.
    """
    with _serve(tmp_path, poll_seconds="1") as (base, config_path):
        before = _sample_two(base)
        (old_etag,) = set(before.values())

        new_etag = _add_a_collection(config_path)
        assert new_etag != old_etag

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            after = _sample(base)
            if len(after) >= 2 and set(after.values()) == {new_etag}:
                break
            time.sleep(0.5)
        else:
            raise AssertionError(
                f"the workers did not converge on {new_etag}: {after}"
            )

        # The new collection is served too, whichever worker answers.
        ids = {
            c["id"]
            for c in httpx.get(
                f"{base}/geoapi/collections?f=json", timeout=10
            ).json()["collections"]
        }
        assert "lakes-bis" in ids
