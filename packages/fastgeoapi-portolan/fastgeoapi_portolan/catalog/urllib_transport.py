"""The reference transport: the standard library reads http(s) URLs, file URLs and local paths.

A bucket URL needs a transport that knows how to sign for it.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from fastgeoapi_portolan.catalog.locations import is_url
from fastgeoapi_portolan.catalog.protocols import MAX_DOCUMENT_BYTES


def _capped(location: str, stream: BinaryIO) -> bytes:
    limit = MAX_DOCUMENT_BYTES
    body = stream.read(limit + 1)
    if len(body) > limit:
        raise OSError(f"{location} is larger than {limit} bytes")
    return body


class UrllibTransport:
    """Reads a document with urllib, or from disk."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def read(self, location: str) -> bytes:
        """The bytes of the document at ``location``.

        A 404 or a 410 raises ``FileNotFoundError``, as a missing file does.
        """
        scheme = urlsplit(location).scheme.lower() if is_url(location) else ""
        if scheme in ("http", "https"):
            return self._fetch(location)
        if scheme == "file":
            return self._open(location, Path(urllib.request.url2pathname(urlsplit(location).path)))
        if scheme:
            raise OSError(f"{location}: the {scheme} scheme needs another transport")
        return self._open(location, Path(location))

    def _fetch(self, location: str) -> bytes:
        try:
            # The scheme is http or https: read() checked it.
            with urllib.request.urlopen(location, timeout=self.timeout) as response:  # ruff: ignore[suspicious-url-open-usage] # nosec B310
                return _capped(location, response)
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                raise FileNotFoundError(f"{location}: HTTP {error.code}") from error
            raise

    @staticmethod
    def _open(location: str, path: Path) -> bytes:
        with path.open("rb") as file:
            return _capped(location, file)
