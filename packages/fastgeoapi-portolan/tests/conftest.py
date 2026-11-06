"""Fixtures shared by the tests of the package."""

from __future__ import annotations

import os
import socket
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import time
from collections.abc import Iterator

import pytest


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def s3_endpoint() -> Iterator[str]:
    """A local S3 on MiniStack, started once for the session.

    The tests that read or write a bucket stay offline while still going
    through signing, addressing and HTTP.
    """
    pytest.importorskip("boto3", reason="the bucket tests need boto3")
    port = _free_port()
    process = subprocess.Popen(  # nosec B603 B607
        ["ministack"],  # ruff: ignore[start-process-with-partial-path]
        env={**os.environ, "GATEWAY_PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        process.kill()
        pytest.fail("MiniStack did not come up within 30s")

    yield f"http://127.0.0.1:{port}"

    process.terminate()
    process.wait(timeout=10)
