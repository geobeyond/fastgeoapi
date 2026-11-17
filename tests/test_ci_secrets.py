"""The tests workflow hands a secret only to the session that uses it."""

from pathlib import Path

import yaml


def test_only_the_safety_session_sees_its_api_key():
    # Every session installs packages from PyPI; one of them going bad must not read the key.
    workflow = yaml.safe_load(Path(".github/workflows/tests.yml").read_text())

    assert workflow["jobs"]["tests"]["env"]["SAFETY_API_KEY"] == (
        "${{ matrix.session == 'safety' && secrets.SAFETY_API_KEY || '' }}"
    )
