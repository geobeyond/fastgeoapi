"""The OpenAPI lint workflow covers both documents, and the OWASP gate gates on both."""

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(".github/workflows/openapi.yml")
DOCUMENTS = ("pygeoapi-openapi.json", "pygeoapi-demo-openapi.json")


@pytest.fixture
def gate(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "owasp_gate", Path(".github/scripts/owasp_gate.py").resolve()
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return module


REPORTS = ("openlint-owasp.json", "openlint-owasp-demo.json")


def _report(findings: list[dict], name: str = "openlint-owasp-demo.json") -> None:
    """Write ``findings`` to the report ``name`` and an empty list to the other."""
    for report in REPORTS:
        Path(report).write_text(json.dumps(findings if report == name else []))


def _finding(code: str, source: str, severity: int = 0) -> dict:
    return {
        "code": code,
        "message": code,
        "path": ["paths", "/collections", "get"],
        "severity": severity,
        "source": source,
        "range": {"start": {"line": 0, "character": 0}, "end": {"line": 0, "character": 0}},
    }


def test_an_unaccepted_error_in_the_demo_document_fails_the_gate(gate):
    _report([_finding("owasp:api3:2023-no-additionalProperties", "/w/pygeoapi-demo-openapi.json")])

    assert gate.main() == 1


def test_an_accepted_error_in_the_demo_document_passes(gate):
    _report([_finding("owasp:api1:2023-no-numeric-ids", "/w/pygeoapi-demo-openapi.json")])

    assert gate.main() == 0


def test_an_error_in_a_remote_document_never_gates(gate):
    _report(
        [_finding("owasp:api3:2023-no-additionalProperties", "https://schemas.opengis.net/x.yaml")]
    )

    assert gate.main() == 0


def test_a_missing_report_fails_the_gate(gate):
    _report([])
    Path("openlint-owasp-demo.json").unlink()

    assert gate.main() == 1


def test_a_finding_without_a_source_fails_the_gate(gate):
    finding = _finding("owasp:api4:2023-array-limit", "/w/pygeoapi-demo-openapi.json", 1)
    del finding["source"]
    _report([finding])

    assert gate.main() == 1


def _steps(job: str) -> str:
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return "\n".join(step.get("run", "") for step in jobs[job]["steps"])


@pytest.mark.parametrize("job", ["openlint-oas", "openlint-owasp"])
def test_each_job_lints_both_documents_built_from_the_lock(job):
    run = _steps(job)

    assert "uv sync --locked" in run
    assert "pip install" not in run
    assert "DEV_PYGEOAPI_CONFIG=pygeoapi-config.demo.yml" in run
    # One document per invocation: given two, OpenLint 1.0.0 reports
    # findings without their source.
    linted = re.findall(r"openlint lint (\S+) \\", run)
    assert sorted(linted) == sorted(DOCUMENTS)
