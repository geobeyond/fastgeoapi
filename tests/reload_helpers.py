"""Trigger a configuration reload from a test, and wait for its outcome.

`GET /admin/config/reload` reports a status and the **last** outcome, and
that outcome outlives the next trigger: until the new work finishes, the
endpoint still describes the reload before it. Polling for an expected
value is therefore ambiguous in both directions — it can be satisfied by
the previous answer, and when the previous answer differs it can burn a
whole deadline and report a timeout for work that was proceeding
normally.

So the wait anchors on what the endpoint said *before* the trigger, and
returns the first outcome that is not that one. A reload that genuinely
fails comes back as `failed` for the caller to assert on, rather than as
a deadline nobody can read.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

PATH = "/admin/config/reload"


class _Client(Protocol):
    def get(self, path: str) -> Any: ...
    def post(self, path: str) -> Any: ...


def reload_now(client: _Client, timeout: float = 60.0) -> dict:
    """Ask for a reload and return the outcome it produced.

    The timeout is generous on purpose. It is not the thing under test:
    a reload rebuilds the whole application, and under a full test run
    the machine is busy enough that a tight deadline fails for reasons
    that have nothing to do with the code. What the deadline is for is
    saying something useful when it expires, which is why the message
    reports the status and whether the outcome ever moved.
    """
    previous = client.get(PATH).json().get("last") or {}

    response = client.post(PATH)
    assert response.status_code == 202, f"the reload was refused: {response.status_code}"

    deadline = time.monotonic() + timeout
    state: dict = {}
    last: dict = {}
    while time.monotonic() < deadline:
        state = client.get(PATH).json()
        last = state.get("last") or {}
        if last and last != previous:
            return last
        time.sleep(0.05)

    raise AssertionError(
        f"no new reload outcome within {timeout}s: status {state.get('status')!r}, "
        f"last still {last or None}"
    )
