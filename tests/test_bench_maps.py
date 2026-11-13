"""The summary of a map benchmark run."""

import importlib.util
from pathlib import Path

import pytest


def _bench():
    spec = importlib.util.spec_from_file_location("bench_maps", Path("scripts/bench_maps.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_summary_counts_throughput_percentiles_and_statuses():
    latencies = [i / 100 for i in range(1, 101)]  # 0.01 .. 1.00 s
    statuses = [200] * 95 + [503] * 5

    summary = _bench().summarise(latencies, statuses, elapsed=10.0)

    assert summary["requests"] == 100
    assert summary["req_s"] == pytest.approx(10.0)
    assert (summary["p50"], summary["p95"], summary["p99"]) == (0.5, 0.95, 0.99)
    assert summary["statuses"] == {"200": 95, "503": 5}
