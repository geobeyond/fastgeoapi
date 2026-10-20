"""rashid, the Portolan validator, reaches the kit's verdicts on the rules it checks with JSON Schema."""

from __future__ import annotations

from dataclasses import fields
from importlib.metadata import version

import pytest

from fastgeoapi_portolan.catalog.testing import write_fixtures

rashid = pytest.importorskip("rashid")
# The schemas come from rashid 0.3; portolan-cli brings an older one along.
if tuple(int(part) for part in version("rashid").split(".")[:2]) < (0, 3):
    pytest.skip("the schema rules are compared with rashid 0.3", allow_module_level=True)

# STAC core, declared extensions, and the Portolan profile schema.
SCHEMA_RULES = frozenset({"PTL-STR-001", "PTL-EXT-001", "PTL-SCH-001"})

# (object id, JSON Pointer) of what rashid rejects; every other case passes.
# rashid holds a catalog that declares no profile to Portolan v0.2.0.
REJECTED = {
    "nonconforming": {("untitled", "")},
    "plain_stac": {("plain-stac", "/stac_extensions"), ("roads", "/stac_extensions")},
}


def test_rashid_agrees_on_the_schema_rules(tmp_path):
    fixtures = write_fixtures(tmp_path)

    for case in fields(fixtures):
        report = rashid.validate(getattr(fixtures, case.name), schema=True, data=False, live=False)
        found = {
            (finding.object_id, finding.json_pointer)
            for finding in report.findings
            if finding.rule_id in SCHEMA_RULES
        }

        assert found == REJECTED.get(case.name, set()), case.name
