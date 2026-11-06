"""Reading a configuration document, and writing it back only if nobody changed it meanwhile.

The version of a document tells two readings apart: the modification
time and the size of a local file, the ETag and the version of an object.
A write checks it first, and a document that changed since it was read is
left as it is, with ``ConcurrentEditError``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import obstore
from obstore.exceptions import PreconditionError

from fastgeoapi_portolan.catalog.locations import is_url
from fastgeoapi_portolan.storage import store_and_key

if TYPE_CHECKING:
    from obstore import UpdateVersion


@dataclass(frozen=True)
class Document:
    """A configuration document as it was read, with the version it had."""

    location: str
    text: str
    version: tuple[str, ...]


class ConcurrentEditError(RuntimeError):
    """The document changed between its reading and its writing."""


def _changed(location: str) -> ConcurrentEditError:
    return ConcurrentEditError(f"{location} changed since it was read: not written")


def _version(stat: os.stat_result) -> tuple[str, ...]:
    return (str(stat.st_mtime_ns), str(stat.st_size))


def _object(location: str, store_options: Mapping[str, Any] | None, store: Any) -> tuple[Any, str]:
    return (store, location) if store is not None else store_and_key(location, store_options)


def read_document(
    location: str, store_options: Mapping[str, Any] | None = None, *, store: Any = None
) -> Document:
    """The document at ``location``, a local path or an object URL.

    ``store`` reads ``location`` as a key of that store instead.
    """
    if store is None and not is_url(location):
        with Path(location).expanduser().open("rb") as file:
            data = file.read()
            # The version of the file that was read, even if a new one replaces it.
            version = _version(os.fstat(file.fileno()))
        return Document(location, data.decode("utf-8"), version)
    target, key = _object(location, store_options, store)
    result = obstore.get(target, key)
    meta = result.meta
    version = (meta.get("e_tag") or "", meta.get("version") or "")
    return Document(location, bytes(result.bytes()).decode("utf-8"), version)


def _write_file(document: Document, text: str) -> None:
    # A symbolic link stays one: the file it points to is the one replaced.
    path = Path(document.location).expanduser().resolve()
    if _version(path.stat()) != document.version:
        raise _changed(document.location)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        shutil.copymode(path, temporary)
        # Checked again just before the swap, so the window is the rename alone.
        if _version(path.stat()) != document.version:
            raise _changed(document.location)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def write_document(
    document: Document,
    text: str,
    store_options: Mapping[str, Any] | None = None,
    *,
    store: Any = None,
) -> None:
    """Write ``text`` over ``document``, if it is still the version that was read.

    A local file is replaced in one rename; an object is put on the
    condition that its ETag and version have not changed.
    """
    if store is None and not is_url(document.location):
        _write_file(document, text)
        return
    e_tag, version = (*document.version, "", "")[:2]
    mode: UpdateVersion = {}
    if e_tag:
        mode["e_tag"] = e_tag
    if version:
        mode["version"] = version
    if not mode:
        raise ValueError(f"{document.location}: the store gives no version to write against")
    target, key = _object(document.location, store_options, store)
    try:
        obstore.put(target, key, text.encode("utf-8"), mode=mode)
    except PreconditionError as error:
        raise _changed(document.location) from error
