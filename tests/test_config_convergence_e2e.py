"""Two real uvicorn workers, one configuration source, and whether they agree.

Everything else in the suite runs the app in process, where there is one
copy of the configuration by construction. Issue #455 is about the other
case: `uvicorn --workers 2` gives every worker its own memory, the reload
webhook reaches whichever process accepts the connection, and the other
keeps serving the previous revision. That cannot be seen without two
processes, so this file starts them.

Workers are told apart by the opaque ``instance`` the authenticated
status endpoint reports, and the revision each one serves by its
``etag``. Sampling goes through the same socket uvicorn shares between
the workers, so "we saw two instances" is a lower bound rather than a
count — the kernel decides who accepts — and both tests say so where
they rely on it.
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
from contextlib import contextmanager
from pathlib import Path

import httpx
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
    assert etag is not None, "a local file always carries an ETag (inode-mtime-size)"
    return etag


@contextmanager
def _serve(tmp_path: Path, poll_seconds: str, workers: int = 2) -> Iterator[tuple[str, Path]]:
    """A real server: the CLI's uvicorn, `workers` processes, config on disk."""
    config_path = tmp_path / "pygeoapi-config.yml"
    config_path.write_text(Path(REPO, "tests/data/pygeoapi-config.yml").read_text())
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
    # Our own interpreter and our own module: nothing untrusted here.
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


def _wait_ready(base: str, server: subprocess.Popen, log: Path, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise AssertionError(f"the server exited early:\n{log.read_text()[-3000:]}")
        try:
            if httpx.get(f"{base}/readyz", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise AssertionError(f"the server was not ready within {timeout}s:\n{log.read_text()[-3000:]}")


def _sample(base: str, rounds: int) -> dict[str, str]:
    """`instance -> etag` for as many workers as answered.

    One connection per request, closed each time, so the kernel hands
    successive requests to whichever worker is accepting; with two of
    them a few dozen rounds reach both in practice, and the callers check
    that they did rather than assume it.
    """
    seen: dict[str, str] = {}
    for _ in range(rounds):
        body = httpx.get(f"{base}{STATUS}", headers={"Connection": "close"}, timeout=5).json()
        seen[body["instance"]] = body["etag"]
    return seen


def _add_a_collection(config_path: Path) -> str:
    config = yaml.safe_load(config_path.read_text())
    config["resources"]["lakes-bis"] = copy.deepcopy(config["resources"]["lakes"])
    config["resources"]["lakes-bis"]["title"] = {"en": "Lakes bis"}
    config_path.write_text(yaml.safe_dump(config))
    return _etag_of(config_path)


def test_the_defect_the_issue_describes(tmp_path):
    """With the poll off, the webhook updates one worker and not the other.

    This is #455 reproduced, and it is the red that gives the next test
    its meaning: were the workers to agree here, convergence would be
    testing nothing.
    """
    with _serve(tmp_path, poll_seconds="0") as (base, config_path):
        before = _sample(base, 30)
        assert len(before) >= 2, f"only one worker answered before: {before}"
        (old_etag,) = set(before.values())

        new_etag = _add_a_collection(config_path)
        assert new_etag != old_etag

        assert httpx.post(f"{base}{STATUS}", timeout=10).status_code == 202
        # Give the one worker that took the POST time to rebuild.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            after = _sample(base, 30)
            if new_etag in after.values():
                break
            time.sleep(0.5)
        else:
            raise AssertionError(f"no worker ever served the new revision: {after}")

        assert len(after) >= 2, f"only one worker answered after the reload: {after}"
        assert set(after.values()) == {old_etag, new_etag}, (
            f"expected the workers to disagree — one reloaded, one not — but they report {after}"
        )


def test_every_worker_converges_to_the_source(tmp_path):
    """With the poll on, a new revision reaches every worker, webhook or not.

    Nobody POSTs here. The file changes, and within the interval plus a
    margin every instance that answers serves the new ETag. "Every
    instance that answers" is what the sampling can promise: at least two
    are required, so the assertion is about more than one process.
    """
    with _serve(tmp_path, poll_seconds="1") as (base, config_path):
        before = _sample(base, 30)
        assert len(before) >= 2, f"only one worker answered before: {before}"
        (old_etag,) = set(before.values())

        new_etag = _add_a_collection(config_path)
        assert new_etag != old_etag

        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            after = _sample(base, 30)
            if len(after) >= 2 and set(after.values()) == {new_etag}:
                break
            time.sleep(0.5)
        else:
            raise AssertionError(f"the workers did not converge on {new_etag}: {after}")

        # And the new collection is actually served, by whoever answers.
        ids = {
            c["id"]
            for c in httpx.get(f"{base}/geoapi/collections?f=json", timeout=10).json()[
                "collections"
            ]
        }
        assert "lakes-bis" in ids
