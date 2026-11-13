"""Both images install the locked packages only if their files match the hashes in uv.lock."""

import re
from pathlib import Path

import pytest

DOCKERFILES = ("Dockerfile", "Dockerfile.flyio")


def _command(dockerfile: str, program: str) -> str:
    """The command of the image that runs `program`, its continued lines joined."""
    lines = Path(dockerfile).read_text().splitlines()
    text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    text = text.replace("\\\n", " ")
    commands = [part for part in re.split(r"&&|\n", text) if program in part]
    assert len(commands) == 1, f"{dockerfile} runs {program} {len(commands)} times"
    return " ".join(commands[0].split())


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_the_exported_requirements_keep_the_lock_hashes(dockerfile):
    assert "--no-hashes" not in _command(dockerfile, "uv export")


@pytest.mark.parametrize("dockerfile", DOCKERFILES)
def test_the_install_refuses_a_file_whose_hash_does_not_match(dockerfile):
    assert "--require-hashes" in _command(dockerfile, "uv pip install")
