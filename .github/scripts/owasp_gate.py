#!/usr/bin/env python3
"""Report and gate the OWASP API Security findings for the OpenAPI document.

Replaces a shell summary that grepped for `" error "` in Spectral's text
output. When the ruleset broke and Spectral aborted before validating
anything, that grep found no matches in `"Error running Spectral!"` and
the job reported *zero errors, zero warnings* — a clean result it had
never measured. So the first thing checked here is that the lint produced
usable output at all; an empty or unparseable report fails the build
rather than reading as success.

Findings are split by source. Spectral resolves `$ref`s into the remote
OGC schemas, and those documents predate the rules; that noise is
reported but never gates. Only findings in our own generated document
can fail the build.

Known errors in our document are listed in ACCEPTED with the reason they
are tolerated. The gate is a ratchet: anything outside that list fails,
so the set can shrink but not silently grow.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from collections import Counter

REPORT = pathlib.Path("spectral-owasp.json")
DOCUMENT = "pygeoapi-openapi.json"

SEVERITY = {0: "error", 1: "warning", 2: "info", 3: "hint"}

# Errors in our own document that we accept today, each with the reason.
# Removing an entry is an improvement; adding one is a decision that
# should be argued in review.
ACCEPTED: dict[str, str] = {
    "owasp:api1:2023-no-numeric-ids": (
        "The flagged parameters are `id` and `stn_id`, queryables derived "
        "from the demo datasets, which happen to have integer keys. This "
        "reflects the sample data, not an API design choice: a deployment "
        "over UUID-keyed data would not raise it."
    ),
    "owasp:api8:2023-no-server-http": (
        "The server URL is whatever PYGEOAPI_BASEURL is set to, and CI "
        "generates the document against http://localhost. The deployed "
        "service is served over https, so gating on this would fail the "
        "build for a property of the build environment."
    ),
}

# Fixed rather than accepted, on 2026-08-12 — listed so nobody re-adds them
# as "known issues":
#   owasp:api9:2023-inventory-access       servers[0].x-internal now declared
#   owasp:api9:2023-inventory-environment  environment named from ENV_STATE
#   owasp:api2:2023-jwt-best-practices     the scheme now describes what is
#                                          enforced, and what only holds when
#                                          issuer/audience are configured


def emit(summary: list[str]) -> None:
    """Write the report to the job summary, or stdout when run locally."""
    text = "\n".join(summary)
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as handle:
            handle.write(text + "\n")


def main() -> int:
    """Parse the Spectral report, print the summary, and gate on our errors."""
    if not REPORT.exists() or not REPORT.stat().st_size:
        emit(
            [
                "# 🔒 OWASP API Security Top 10",
                "",
                f"**The lint produced no report** (`{REPORT}` missing or empty).",
                "Treating this as a failure: a check that cannot run must not "
                "read as a check that passed.",
            ]
        )
        return 1

    try:
        findings = json.loads(REPORT.read_text())
    except json.JSONDecodeError as error:
        emit(
            [
                "# 🔒 OWASP API Security Top 10",
                "",
                f"**The report is not valid JSON**: {error}",
                "Spectral most likely aborted before validating — check the "
                "ruleset for rule names that no longer exist upstream.",
            ]
        )
        return 1

    def is_ours(finding: dict) -> bool:
        return (finding.get("source") or "").endswith(DOCUMENT)

    ours = [f for f in findings if is_ours(f)]
    remote = [f for f in findings if not is_ours(f)]
    our_errors = [f for f in ours if f["severity"] == 0]
    unexpected = [f for f in our_errors if f["code"] not in ACCEPTED]

    summary = [
        "# 🔒 OWASP API Security Top 10",
        "",
        "| Source | Errors | Warnings |",
        "|---|---|---|",
        f"| **Our document** | {sum(1 for f in ours if f['severity'] == 0)} "
        f"| {sum(1 for f in ours if f['severity'] == 1)} |",
        f"| Remote OGC schemas | {sum(1 for f in remote if f['severity'] == 0)} "
        f"| {sum(1 for f in remote if f['severity'] == 1)} |",
        "",
        "Findings in the remote schemas are reported but never gate: they come "
        "from documents we resolve and do not control.",
        "",
    ]

    if our_errors:
        summary += ["## Errors in our document", ""]
        for code, count in Counter(f["code"] for f in our_errors).most_common():
            mark = "✅ accepted" if code in ACCEPTED else "❌ **new**"
            summary.append(f"- `{code}` x{count} — {mark}")
            if code in ACCEPTED:
                summary.append(f"  - {ACCEPTED[code]}")
        summary.append("")

    if unexpected:
        summary += [
            "## ❌ Failing",
            "",
            "These are not in the accepted list. Either fix them, or add an "
            "entry to `ACCEPTED` in `.github/scripts/owasp_gate.py` with the "
            "reason — an argument someone can disagree with in review.",
            "",
        ]
        for finding in unexpected:
            where = ".".join(str(p) for p in finding.get("path", []))
            summary.append(f"- `{finding['code']}` at `{where}`: {finding['message']}")
        emit(summary)
        return 1

    summary.append("✅ No unaccepted errors in our document.")
    emit(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
