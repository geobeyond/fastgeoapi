"""The root document of a catalog, and the references its documents hold."""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

CATALOG = "catalog.json"

_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def is_url(location: str) -> bool:
    """Whether ``location`` is a URL rather than a path."""
    return _SCHEME.match(location) is not None


def root_document(location: str) -> str:
    """The ``catalog.json`` that ``location`` names.

    A directory, or a URL that does not end in ``.json``, gets
    ``catalog.json`` appended. A local path is made absolute, with its
    symbolic links resolved, so the same catalog always carries the same
    name: the provenance of an ingested collection is compared on it.
    """
    if is_url(location):
        return location if location.endswith(".json") else f"{location.rstrip('/')}/{CATALOG}"
    path = Path(location).expanduser().resolve()
    return str(path if path.suffix == ".json" else path / CATALOG)


def resolve(document: str, href: str) -> str:
    """``href``, found in ``document``, as an absolute location.

    A relative STAC link resolves against the document that holds it. A
    local one also has its symbolic links resolved, as the root has, so a
    document reached by two paths has one name in the walk.
    Every URL scheme resolves the same way: on the path, keeping the scheme
    and the host, which for an object store is the bucket. ``urljoin`` does that
    only for the schemes it knows, and ``s3://`` is not one of them.
    """
    if is_url(href):
        return href
    if not is_url(document):
        return str((Path(document).parent / href).resolve())
    base = urlsplit(document)
    target = urlsplit(href)
    path = target.path
    if not path.startswith("/"):
        path = posixpath.join(posixpath.dirname(base.path), path)
    return urlunsplit(
        (base.scheme, base.netloc, posixpath.normpath(path), target.query, target.fragment)
    )
