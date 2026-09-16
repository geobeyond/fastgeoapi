"""Why the demo's configuration names a job manager.

pygeoapi puts `/jobs`, `/jobs/{jobId}` and `/jobs/{jobId}/results` in the
OpenAPI document only when the configured manager reports `is_async`
(``api/processes.py``, 0.24). The routes are served either way — measured
against the demo on 2026-09-16, `GET /jobs` answered 200 and an unknown
id answered 404 — and OGC API - Processes Part 1 Requirement 35 states
the path unconditionally: "The server SHALL support the HTTP GET
operation at the path /jobs/{jobID}".

So the gate is a documentation gap, and it is not cosmetic: the MCP tools
are generated from the document, so without it an agent can start an
execution and has no tool to ask how it went. These tests pin the
mechanism the demo's `manager` block exists for.
"""

from __future__ import annotations

import copy

import pytest

JOB_PATHS = ("/jobs", "/jobs/{jobId}", "/jobs/{jobId}/results")


@pytest.fixture
def config_with_a_process() -> dict:
    """The test configuration, reduced to its process.

    Built from the file rather than by hand: pygeoapi's document
    generation reads metadata keys it never declares as required, so a
    minimal dict written here drifts into `KeyError` at the first
    upstream change.
    """
    from pathlib import Path

    from pygeoapi.util import yaml_load

    config = copy.deepcopy(yaml_load(Path("tests/data/pygeoapi-config.yml").open()))
    config["resources"] = {
        name: resource
        for name, resource in config["resources"].items()
        if resource.get("type") == "process"
    }
    assert config["resources"], "the test configuration should carry a process"
    return config


def test_without_a_manager_the_job_endpoints_are_undocumented(config_with_a_process):
    """The gap this configuration block exists to close."""
    from app.pygeoapi.factory import build_openapi

    doc = build_openapi(config_with_a_process)

    assert [p for p in JOB_PATHS if p in doc["paths"]] == []


def test_a_manager_that_is_async_documents_them(config_with_a_process, tmp_path):
    from app.pygeoapi.factory import build_openapi

    config = copy.deepcopy(config_with_a_process)
    config["server"]["manager"] = {
        "name": "TinyDB",
        "connection": str(tmp_path / "manager.db"),
        "output_dir": str(tmp_path),
    }

    doc = build_openapi(config)

    assert [p for p in JOB_PATHS if p in doc["paths"]] == list(JOB_PATHS)


def test_the_demo_configuration_names_one():
    """The demo declares Processes core, so it has to describe the jobs."""
    from pathlib import Path

    from pygeoapi.util import yaml_load

    config = yaml_load(Path("pygeoapi-config.demo.yml").open())

    assert config["server"]["manager"]["name"] == "TinyDB"
