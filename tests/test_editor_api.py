"""The endpoints an editor calls, and the one rule that matters most.

`PUT` must refuse a document it would not be able to serve, **without
writing it**. An editor that happily saves a configuration which then
stops the server would be worse than no editor at all: it would have
carried the operator confidently into the failure.

Everything else here is in service of that — reading the document as
written, saying what is wrong with it, and building it for real before
anyone commits to it.
"""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.editor.app import EDITOR_TOKEN_HEADER, build_authoring_app

SOURCE = Path("tests/data/pygeoapi-config.yml").read_text()


@pytest.fixture
def editor(tmp_path):
    """An editor pointed at a throwaway copy of the configuration."""
    target = tmp_path / "pygeoapi-config.yml"
    target.write_text(SOURCE)
    app = build_authoring_app(host="127.0.0.1", source=str(target))
    client = TestClient(app)
    client.headers[EDITOR_TOKEN_HEADER] = app.state.editor_token
    return client, target


def test_the_document_is_returned_as_written(editor):
    """Placeholders included: this is the source, not the effective form."""
    client, _ = editor

    body = client.get("/editor/config").json()

    assert "${PORT}" in body["document"], body["document"][:200]


def test_validation_answers_both_questions(editor):
    """Source and effective are different questions with different answers."""
    client, _ = editor

    body = client.post("/editor/validate", json={"document": SOURCE}).json()

    assert body["source"]["ok"], body["source"]
    assert "variables" in body["effective"], body["effective"]


def test_a_dry_run_reports_the_collections(editor):
    client, _ = editor

    body = client.post("/editor/dry-run", json={"document": SOURCE}).json()

    assert body["ok"], body["problems"]
    assert {"obs", "lakes"} <= set(body["collections"]), body["collections"]


def test_saving_an_invalid_document_writes_nothing(editor):
    """The rule the whole surface exists to respect.

    Refusing is not enough — refusing *after* writing would leave the
    bucket holding a configuration that cannot start, one webhook call
    away from taking the service down.
    """
    client, target = editor
    before = target.read_text()

    response = client.put("/editor/config", json={"document": "resources: [oops]"})

    assert response.status_code == 422, response.text
    assert target.read_text() == before, "the document on disk was modified"


def test_saving_a_valid_document_writes_it(editor):
    client, target = editor
    changed = SOURCE.replace("title: Observations", "title: Renamed observations", 1)

    response = client.put("/editor/config", json={"document": changed})

    assert response.status_code == 200, response.text
    assert "Renamed observations" in target.read_text()


def test_saving_does_not_activate_anything(editor):
    """Writing and putting into service stay two gestures (ADR-0008)."""
    client, _ = editor

    body = client.put("/editor/config", json={"document": SOURCE}).json()

    assert body["activated"] is False, body


def test_saving_says_what_it_did_not_check(editor):
    """ "Saved" must not be readable as "verified".

    A dry run costs seconds against a remote dataset, so it is not done
    on every save — an editor that made people wait would teach them to
    route around it. What is left unchecked is therefore stated, rather
    than left to be assumed.
    """
    client, _ = editor

    body = client.put("/editor/config", json={"document": SOURCE}).json()

    assert body["checked"] == ["source", "effective"], body
    assert any("dry-run" in item for item in body["not_checked"]), body
