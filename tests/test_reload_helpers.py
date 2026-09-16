"""Waiting for a reload, without mistaking the previous one for it.

`GET /admin/config/reload` reports the status and the **last** outcome,
and that last one survives the next trigger until the new work finishes.
A wait that polls for an expected value can therefore be answered by the
reload before this one — passing for the wrong reason — or, when the
value differs, spend its whole deadline looking at a stale answer and
call that a timeout, which is what it reports even while the work is
still running perfectly well.

So the helper anchors on the previous outcome instead of on a deadline
alone, and says which of the two happened when it gives up.
"""

from __future__ import annotations

from typing import Any

import pytest

PATH = "/admin/config/reload"


class _Client:
    """A status endpoint that answers a scripted sequence of states."""

    def __init__(self, states: list[dict[str, Any]]) -> None:
        self._states = states
        self.posts = 0

    def post(self, path: str):
        assert path == PATH
        self.posts += 1
        return _Response(202, {"status": "started"})

    def get(self, path: str):
        assert path == PATH
        state = self._states[0] if len(self._states) == 1 else self._states.pop(0)
        return _Response(200, state)


class _Response:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict:
        return self._payload


APPLIED = {"outcome": "applied", "at": "2026-09-17T09:00:00+00:00", "etag": "b"}
EARLIER = {"outcome": "applied", "at": "2026-09-16T09:00:00+00:00", "etag": "a"}
FAILED = {"outcome": "failed", "at": "2026-09-17T09:00:01+00:00", "error": "boom"}


def test_the_previous_outcome_is_not_the_answer():
    """The trap: the same outcome, from the reload before this one."""
    from tests.reload_helpers import reload_now

    client = _Client(
        [
            {"status": "idle", "last": EARLIER},  # read before the trigger
            {"status": "running", "last": EARLIER},
            {"status": "running", "last": EARLIER},
            {"status": "idle", "last": APPLIED},
        ]
    )

    assert reload_now(client)["at"] == APPLIED["at"]


def test_the_trigger_happens_once():
    from tests.reload_helpers import reload_now

    client = _Client([{"status": "idle", "last": EARLIER}, {"status": "idle", "last": APPLIED}])

    reload_now(client)

    assert client.posts == 1


def test_a_failure_comes_back_as_a_failure_not_as_a_timeout():
    """The caller asserts the outcome; it should see `failed`, not a deadline."""
    from tests.reload_helpers import reload_now

    client = _Client([{"status": "idle", "last": EARLIER}, {"status": "idle", "last": FAILED}])

    assert reload_now(client)["outcome"] == "failed"


def test_giving_up_says_whether_the_work_was_still_running():
    """A timeout has to distinguish slow from stuck, or it teaches nothing."""
    from tests.reload_helpers import reload_now

    client = _Client([{"status": "running", "last": EARLIER}])

    with pytest.raises(AssertionError) as raised:
        reload_now(client, timeout=0.2)

    assert "running" in str(raised.value)


def test_a_first_ever_reload_has_no_previous_outcome():
    """`last` is null until something has run."""
    from tests.reload_helpers import reload_now

    client = _Client([{"status": "idle", "last": None}, {"status": "idle", "last": APPLIED}])

    assert reload_now(client)["outcome"] == "applied"
