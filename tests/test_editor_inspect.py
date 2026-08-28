"""What the editor can tell an operator about a configuration.

Three questions, three answers, all without HTTP so they can be tested
and reused (the CLI and a CI check want them too):

- is the document I am editing well formed?
- is what will actually run well formed?
- does it build?

The distinction between the first two is not pedantry. The document an
operator edits carries `${VAR}` placeholders; the one that runs has them
resolved. `port: ${PORT}` is a string where the schema wants an integer,
so validating the source as if it were the effective form would report a
false error on a perfectly good deployment — and push whoever reads it
to hardcode what was parameterised on purpose.
"""

from pathlib import Path

import pytest

from app.editor.inspect import dry_run, validate_effective, validate_source

SOURCE = Path("pygeoapi-config.yml").read_text()
TEST_SOURCE = Path("tests/data/pygeoapi-config.yml").read_text()


def test_source_validation_accepts_placeholders():
    """The shipped document validates as a source, placeholders and all."""
    outcome = validate_source(SOURCE)

    assert outcome.ok, outcome.problems


def test_source_validation_still_catches_real_mistakes():
    """Forgiving placeholders must not mean forgiving everything."""
    broken = SOURCE.replace("resources:", "resources: [oops]\nunused:", 1)

    outcome = validate_source(broken)

    assert not outcome.ok
    assert any("resources" in problem for problem in outcome.problems), outcome.problems


def test_effective_validation_reports_the_variables_it_used(monkeypatch):
    """An outcome nobody can reproduce is not an outcome.

    The effective form depends on the environment doing the resolving —
    the editor's, not the deployment's. Saying which values were
    substituted is what lets a reader tell the two apart.
    """
    monkeypatch.setenv("PORT", "5000")

    outcome = validate_effective(SOURCE)

    assert outcome.ok, outcome.problems
    assert outcome.variables.get("PORT") == "5000", outcome.variables


def test_effective_validation_names_the_missing_variable(monkeypatch):
    """A placeholder with nothing behind it is a configuration problem."""
    monkeypatch.delenv("PORT", raising=False)

    outcome = validate_effective(SOURCE)

    assert not outcome.ok
    assert any("PORT" in problem for problem in outcome.problems), outcome.problems


def test_dry_run_reports_what_was_built():
    """Green has to say what it means: which collections stood up."""
    outcome = dry_run(TEST_SOURCE)

    assert outcome.ok, outcome.problems
    assert {"obs", "lakes"} <= set(outcome.collections), outcome.collections


def test_dry_run_names_the_provider_that_fails():
    """The message an operator can act on names the resource, not the trace.

    A provider pointing at something unreadable is the most common way a
    configuration that validates still does not work — and the reason a
    dry-run earns its place beside validation.
    """
    broken = TEST_SOURCE.replace(
        "data: tests/data/ne_110m_lakes.geojson",
        "data: tests/data/does-not-exist.geojson",
        1,
    )

    outcome = dry_run(broken)

    assert not outcome.ok
    assert any("lakes" in problem for problem in outcome.problems), outcome.problems


def test_dry_run_says_which_environment_it_used():
    """It answers "does this build here", never "will this work there".

    The build uses the editor's environment and credentials, not the
    deployment's. An outcome that hides that invites reading a green as
    a guarantee it cannot give.
    """
    outcome = dry_run(TEST_SOURCE)

    assert outcome.variables, "the substituted variables belong in the outcome"


@pytest.mark.parametrize("bad", ["resources: [", "\tnot yaml at all"])
def test_unparseable_input_is_a_problem_not_a_crash(bad):
    """Someone is editing: half-written documents are the normal case."""
    outcome = validate_source(bad)

    assert not outcome.ok
    assert outcome.problems
