"""The generated models must describe the schema that is installed.

The models are derived from pygeoapi's configuration schema, not written
by hand, so the moment upstream moves that schema they describe
something that no longer exists — and nothing else would notice, because
generated code keeps importing and keeps validating, just against the
wrong shape.

The schema declares no version (only an `$id` pointing at master), so
the identity we can check is its content.
"""

import hashlib
from pathlib import Path

import pygeoapi

from app.pygeoapi.config_models.schema_digest import SCHEMA_PATH, SCHEMA_SHA256


def _installed_schema() -> Path:
    return Path(pygeoapi.__file__).parent / "resources/schemas/config/pygeoapi-config-0.x.yml"


def test_the_models_match_the_installed_schema():
    """Red when a pygeoapi upgrade changes the configuration schema."""
    actual = hashlib.sha256(_installed_schema().read_bytes()).hexdigest()

    assert actual == SCHEMA_SHA256, (
        "pygeoapi's configuration schema changed. Regenerate with "
        "`nox -s models`, review the diff, and land it as `feat:` — the "
        "models are a public contract, so a schema change moves the minor. "
        "If a key was removed or tightened, say so in the changelog: at "
        "0.x the version number cannot."
    )


def test_the_committed_copy_matches_the_digest():
    """The copy and the fingerprint must not be able to drift apart.

    The copy exists so a future change can be diffed property by
    property — that is what the changelog needs, and a digest alone
    cannot give. Two records of the same thing, written by the same
    step: this pins that they stay one thing.
    """
    copied = hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest()

    assert copied == SCHEMA_SHA256, (
        "the committed schema copy and its digest disagree — regenerate "
        "with `nox -s models` rather than editing either by hand"
    )
