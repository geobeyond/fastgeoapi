"""The maps group installs the mlnative fork's wheels, on Linux only."""

import tomllib
from pathlib import Path

RELEASE = "https://github.com/francbartoli/mlnative/releases/download/v0.4.0.dev1/"


def _project() -> dict:
    return tomllib.loads(Path("pyproject.toml").read_text())


def test_the_maps_group_brings_mlnative_on_linux_and_pillow():
    group = _project()["dependency-groups"]["maps"]

    # Only where a wheel exists: anywhere else uv would look for the fork on PyPI and fail.
    assert (
        "mlnative==0.4.0.dev1; sys_platform == 'linux' and (platform_machine == 'x86_64' or platform_machine == 'aarch64')"
        in group
    )
    assert any(item.startswith("pillow") for item in group)


def test_mlnative_comes_from_the_fork_release_for_each_linux_machine():
    sources = _project()["tool"]["uv"]["sources"]["mlnative"]
    by_machine = {
        s["marker"].split("platform_machine == ")[1].strip("'"): s["url"] for s in sources
    }

    assert by_machine == {
        "x86_64": RELEASE + "mlnative-0.4.0.dev1-py3-none-manylinux_2_39_x86_64.whl",
        "aarch64": RELEASE + "mlnative-0.4.0.dev1-py3-none-manylinux_2_39_aarch64.whl",
    }
    assert all(s["marker"].startswith("sys_platform == 'linux'") for s in sources)


def test_mlnative_is_not_a_runtime_dependency():
    assert not any("mlnative" in item for item in _project()["project"]["dependencies"])


def test_the_dev_group_has_pillow_for_the_map_tests():
    assert any(item.startswith("pillow") for item in _project()["dependency-groups"]["dev"])
