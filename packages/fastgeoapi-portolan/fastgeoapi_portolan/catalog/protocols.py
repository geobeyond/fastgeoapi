"""What a reader plugs into the walk: a way to fetch documents, and one to check them.

A transport raises ``FileNotFoundError`` for a document that does not
exist and an ``OSError`` for any other failure; the walk turns both into a
skipped document with the reason. Anything else it raises stops the walk.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from fastgeoapi_portolan.catalog.results import Validation


class Transport(Protocol):
    """Reads a whole document, one at a time."""

    def read(self, location: str) -> bytes:
        """The bytes of the document at ``location``."""
        ...


class AsyncTransport(Protocol):
    """Reads a whole document; the driver awaits several at once."""

    async def read(self, location: str) -> bytes:
        """The bytes of the document at ``location``."""
        ...


class SchemaValidator(Protocol):
    """Checks a document against its schemas.

    The document declares its kind in ``type``. ``root_profile`` is the
    Portolan schema the root declares, which applies to a document that
    declares none.
    """

    def validate(self, document: Mapping[str, Any], *, root_profile: str | None) -> Validation:
        """The schema errors in ``document``, and the schemas left unchecked."""
        ...
