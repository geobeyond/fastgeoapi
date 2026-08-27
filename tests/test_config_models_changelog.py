"""The summary a schema change produces for the changelog.

At `0.x` the version number cannot distinguish "new keys are available"
from "your configuration no longer validates" — both land on the minor.
So the changelog carries that difference, and this is the code that
drafts it. Its contract is not "list the diff": it is **put first what
breaks a configuration that works today**.
"""

from scripts.generate_config_models import _summarise_changes


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "properties": {
            "server": {
                "type": "object",
                "properties": properties,
                **({"required": required} if required else {}),
            }
        }
    }


def test_a_removed_key_is_reported_as_no_longer_accepted():
    summary = _summarise_changes(
        _schema({"url": {"type": "string"}, "legacy": {"type": "string"}}),
        _schema({"url": {"type": "string"}}),
    )

    assert any("server.legacy" in line and "no longer accepted" in line for line in summary), (
        summary
    )


def test_a_changed_type_is_reported_with_both_types():
    summary = _summarise_changes(
        _schema({"url": {"type": "object"}}),
        _schema({"url": {"type": "string"}}),
    )

    assert any("server.url" in line and "object" in line and "string" in line for line in summary)


def test_a_key_that_became_required_is_reported():
    """The case a type-only comparison misses entirely.

    A property that already existed, unchanged in type, but is now in
    `required` breaks every configuration that omitted it — exactly as
    hard as a removal, and with no other signal to the operator.
    """
    summary = _summarise_changes(
        _schema({"url": {"type": "string"}, "icon": {"type": "string"}}, required=["url"]),
        _schema({"url": {"type": "string"}, "icon": {"type": "string"}}, required=["url", "icon"]),
    )

    assert any("server.icon" in line and "required" in line for line in summary), summary


def test_breaking_changes_come_before_additions():
    """The ordering is the contract, not a nicety.

    Someone scanning a release note reads the top. What can break a
    running configuration has to be there.
    """
    summary = _summarise_changes(
        _schema({"kept": {"type": "string"}, "legacy": {"type": "string"}}),
        _schema({"kept": {"type": "string"}, "brand_new": {"type": "string"}}),
    )

    removed_at = next(i for i, line in enumerate(summary) if "legacy" in line)
    added_at = next(i for i, line in enumerate(summary) if "brand_new" in line)
    assert removed_at < added_at, summary


def test_an_unchanged_schema_says_nothing():
    """No noise when nothing moved: a summary of zero changes is zero lines."""
    same = _schema({"url": {"type": "string"}})

    assert _summarise_changes(same, same) == []
