"""Where a map renderer reads a collection's data.

The renderer runs in its own process and reads the data itself, by URL:
a file URL for a local object, the public URL for a public one, and a
presigned URL for a private bucket. A presigned URL is renewed between
renders once a fifth of its life is left, so that no signature runs out
halfway through a map.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from pmtiles.reader import Reader


class ObjectUrl:
    """The URL of one data object, for a reader outside this process."""

    def __init__(
        self,
        *,
        local_path: Path | None = None,
        public_url: str | None = None,
        signer: Callable[[timedelta], str] | None = None,
        ttl: timedelta = timedelta(hours=1),
        renew_at: float = 0.2,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Give exactly one of a local path, a public URL or a signer."""
        if sum(value is not None for value in (local_path, public_url, signer)) != 1:
            raise ValueError("give exactly one of local_path, public_url or signer")
        self._local_path = local_path
        self._public_url = public_url
        self._signer = signer
        self._ttl = ttl
        self._renew_at = renew_at
        self._clock = clock
        self._signed: str | None = None
        self._renew_after = 0.0

    def current(self) -> str:
        """The URL to read the object at now, signed again when needed."""
        if self._local_path is not None:
            return f"file://{self._local_path.resolve()}"
        if self._public_url is not None:
            return self._public_url
        if self._signer is None:
            raise RuntimeError("an ObjectUrl without a path or URL needs a signer")
        now = self._clock()
        if self._signed is None or now >= self._renew_after:
            self._signed = self._signer(self._ttl)
            self._renew_after = now + self._ttl.total_seconds() * (1 - self._renew_at)
        return self._signed


class PMTilesSource:
    """A PMTiles archive of vector tiles, read in place."""

    format = "pmtiles"

    def __init__(self, location: ObjectUrl, read: Callable[[int, int], bytes]) -> None:
        """``read(offset, length)`` returns a byte range of the archive.

        The metadata is read through it the first time :meth:`layers` is
        called.
        """
        self._location = location
        self._read = read
        self._layers: list[str] | None = None

    def url(self) -> str:
        """The URL of the archive."""
        return self._location.current()

    def layers(self) -> list[str]:
        """The vector layers the archive metadata declares."""
        if self._layers is None:
            metadata = Reader(self._read).metadata()
            self._layers = [layer["id"] for layer in metadata.get("vector_layers", [])]
        return self._layers
