"""The demo image installs the renderer and the libraries MapLibre Native links."""

from pathlib import Path

LIBRARIES = (
    "libuv1",
    "libvulkan1",
    "mesa-vulkan-drivers",
    "libicu74",
    "libcurl4t64",
    "libpng16-16t64",
    "libjpeg-turbo8",
    "libwebp7",
)


def _dockerfile() -> str:
    return Path("Dockerfile.flyio").read_text()


def test_the_image_installs_the_maps_group():
    assert "--group maps" in _dockerfile()


def test_the_image_installs_the_renderer_libraries():
    text = _dockerfile()
    assert [lib for lib in LIBRARIES if lib not in text] == []
