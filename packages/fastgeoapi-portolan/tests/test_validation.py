"""The schema validator on the kit's documents."""

from __future__ import annotations

import json

import pytest

from fastgeoapi_portolan.catalog.testing import PARTITION, PORTOLAN, write_fixtures
from fastgeoapi_portolan.validation import JsonSchemaValidator

UNBUNDLED_TABLE = "https://stac-extensions.github.io/table/v9.9.9/schema.json"


@pytest.fixture(scope="module")
def validator():
    return JsonSchemaValidator()


@pytest.fixture
def fixtures(tmp_path):
    return write_fixtures(tmp_path)


def _load(path):
    return json.loads(path.read_text())


@pytest.fixture
def roads(fixtures):
    return _load(fixtures.nested.parent / "data" / "roads" / "collection.json")


def test_a_conforming_collection_has_no_findings(validator, roads):
    validation = validator.validate(roads, root_profile=PORTOLAN)

    assert validation.findings == ()
    assert validation.unverified == ()


def test_a_collection_without_a_title_names_the_title(validator, fixtures):
    untitled = _load(fixtures.nonconforming.parent / "untitled" / "collection.json")

    (finding,) = validator.validate(untitled, root_profile=PORTOLAN).findings

    assert "'title'" in finding.message
    assert finding.schema == PORTOLAN
    assert finding.pointer == ""


def test_a_collection_without_the_portolan_uri_fails_under_the_root_profile(validator, roads):
    roads["stac_extensions"] = []

    findings = validator.validate(roads, root_profile=PORTOLAN).findings

    assert [(finding.schema, finding.pointer) for finding in findings] == [
        (PORTOLAN, "/stac_extensions")
    ]


def test_a_plain_stac_collection_is_checked_against_stac_and_its_extensions_only(
    validator, fixtures
):
    roads = _load(fixtures.plain_stac.parent / "roads" / "collection.json")
    del roads["title"]

    assert validator.validate(roads, root_profile=None).findings == ()


def test_an_extension_version_not_bundled_is_unverified(validator, roads):
    roads["stac_extensions"].append(UNBUNDLED_TABLE)

    validation = validator.validate(roads, root_profile=PORTOLAN)

    assert validation.findings == ()
    assert validation.unverified == (UNBUNDLED_TABLE,)


def test_a_stac_version_not_bundled_is_unverified(validator, roads):
    roads["stac_version"] = "1.0.0"

    validation = validator.validate(roads, root_profile=PORTOLAN)

    assert validation.unverified == (
        "https://schemas.stacspec.org/v1.0.0/collection-spec/json-schema/collection.json",
    )


def test_a_document_of_unknown_type_is_a_finding(validator, roads):
    roads["type"] = "Dataset"

    findings = validator.validate(roads, root_profile=PORTOLAN).findings

    assert "/type" in {finding.pointer for finding in findings}


def test_an_item_validates_through_common_json(validator, fixtures):
    buildings = fixtures.partitioned.parent / "buildings"
    item = _load(buildings / "part=0" / "part-0.json")

    assert validator.validate(item, root_profile=PORTOLAN).findings == ()

    # `created` is defined in common.json, which the item schema reaches by $ref.
    item["properties"]["created"] = 5
    findings = validator.validate(item, root_profile=PORTOLAN).findings

    assert [finding.pointer for finding in findings] == ["/properties/created"]


def test_a_partitioned_collection_without_its_glob_fails(validator, fixtures):
    buildings = _load(fixtures.partitioned.parent / "buildings" / "collection.json")
    del buildings["partition:glob"]

    findings = validator.validate(buildings, root_profile=PORTOLAN).findings

    assert {finding.schema for finding in findings} == {PORTOLAN, PARTITION}
    assert all("partition:glob" in finding.message for finding in findings)


def test_a_collection_with_schema_summaries_validates_offline(validator, roads):
    # A summary may be a JSON Schema, checked against the draft-07 meta-schema.
    roads["summaries"] = {"height": {"type": "number", "minimum": 0}}

    assert validator.validate(roads, root_profile=PORTOLAN).findings == ()

    roads["summaries"] = {"height": {"type": "number", "minimum": "zero"}}

    findings = validator.validate(roads, root_profile=PORTOLAN).findings

    assert findings
    assert all(finding.pointer.startswith("/summaries/height") for finding in findings)


def test_the_pointer_escapes_the_keys(validator, roads):
    roads["assets"]["a/b~c"] = {"href": "./x.parquet", "roles": ["data"]}

    findings = validator.validate(roads, root_profile=PORTOLAN).findings

    assert [finding.pointer for finding in findings] == ["/assets/a~1b~0c"]


def test_a_long_message_is_cut(validator, roads):
    # Without the Portolan URI, the message quotes the whole list.
    roads["stac_extensions"] = [f"https://example.org/extension-{n}/schema.json" for n in range(20)]

    (finding,) = validator.validate(roads, root_profile=PORTOLAN).findings

    assert len(finding.message) == 300
    assert finding.message.endswith("...")
