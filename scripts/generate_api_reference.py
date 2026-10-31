"""Write the API reference of the example configuration into the docs.

The OpenAPI document of ``pygeoapi-config.yml`` is built the way the
server builds it, its remote ``$ref`` resolved, and rendered into
Markdown pages by mkdocs-openapi's generator. Zensical does not run that
plugin, so its generator is used as a library here, before the build,
and its stylesheet and script are copied next to the pages.

Run it before ``zensical build``; the pages it writes are not versioned.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import mkdocs_openapi.assets
from mkdocs_openapi.generator import generate_site

CONFIG = Path("pygeoapi-config.yml")
DOCS_DIR = Path("docs")
REFERENCE_DIR = "consumers/reference/api"
CACHE_DIR = Path("docs_build/openapi-refs-cache")
# The placeholders of the example configuration, set only when the
# environment does not already give them.
PLACEHOLDERS = {
    "HOST": "127.0.0.1",
    "PORT": "5000",
    "PYGEOAPI_BASEURL": "https://example.org",
    "FASTGEOAPI_CONTEXT": "/geoapi",
}


@contextmanager
def set_example_environment() -> Generator[None]:
    """Set the placeholders of the example configuration for the time of a block."""
    missing = {name: value for name, value in PLACEHOLDERS.items() if name not in os.environ}
    os.environ.update(missing)
    try:
        yield
    finally:
        for name in missing:
            os.environ.pop(name, None)


def build_example_document(config: Path = CONFIG, cache_dir: Path = CACHE_DIR) -> dict:
    """Build the OpenAPI document of ``config`` with every remote ``$ref`` resolved.

    Parameters
    ----------
    config
        The pygeoapi configuration, with its ``${...}`` placeholders.
    cache_dir
        Where the remote documents the ``$ref`` point to are kept between runs.

    Returns
    -------
    dict
        The document, with only local ``$ref`` left.
    """
    from pygeoapi.util import yaml_load

    from app.pygeoapi.factory import build_openapi
    from app.utils.openapi_resolver import resolve_external_refs

    with set_example_environment(), config.open() as handle:
        loaded = yaml_load(handle)
    return resolve_external_refs(build_openapi(loaded), cache_dir=cache_dir)


def write_reference(document: dict, docs_dir: Path = DOCS_DIR) -> list[Path]:
    """Write the pages of ``document`` under ``docs_dir``, and the assets they use.

    The pages of a previous run are removed first, so an operation that
    left the document leaves the docs too.

    Parameters
    ----------
    document
        An OpenAPI 3 document whose ``$ref`` are all local.
    docs_dir
        The ``docs_dir`` of the site.

    Returns
    -------
    list of Path
        The files written: the pages, the stylesheet and the script.
    """
    target = docs_dir / REFERENCE_DIR
    shutil.rmtree(target, ignore_errors=True)
    site = generate_site(document, output_dir=REFERENCE_DIR, models_dir=f"{REFERENCE_DIR}/models")
    written = []
    for name, content in site.pages.items():
        page = docs_dir / name
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(content)
        written.append(page)
    assets = Path(mkdocs_openapi.assets.__file__).parent
    for source, folder in (
        ("mkdocs-openapi.css", "stylesheets"),
        ("mkdocs-openapi.js", "javascripts"),
    ):
        copy = docs_dir / folder / source
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(assets / source, copy)
        written.append(copy)
    return written


def main() -> int:
    """Build the example document and write its pages into ``docs``."""
    written = write_reference(build_example_document())
    print(f"{len(written)} files written under {DOCS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
