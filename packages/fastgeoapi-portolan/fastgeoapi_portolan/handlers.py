"""What a handler is: it turns one kind of asset in a collection into a fastgeoapi provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from obstore.exceptions import BaseError

from fastgeoapi_portolan.catalog.protocols import MAX_DOCUMENT_BYTES, DocumentTooLargeError
from fastgeoapi_portolan.catalog.walk import MAX_DOCUMENTS
from fastgeoapi_portolan.reader import Collection


@dataclass(frozen=True)
class IngestOptions:
    """What the command line adds to the catalog: storage, columns and reading limits.

    ``id_fields`` and ``geometry_columns`` map a collection id to a column,
    for the collections whose catalog names none.
    ``max_documents`` bounds the items read for a collection, and
    ``max_document_bytes`` the size of each document a handler reads.
    """

    store_options: Mapping[str, Any] = field(default_factory=dict)
    id_fields: Mapping[str, str] = field(default_factory=dict)
    geometry_columns: Mapping[str, str] = field(default_factory=dict)
    max_documents: int = MAX_DOCUMENTS
    max_document_bytes: int = MAX_DOCUMENT_BYTES


@dataclass(frozen=True)
class ProviderMatch:
    """A provider for the resource, and where each of its values came from."""

    provider: dict[str, Any]
    choices: tuple[str, ...]


@dataclass(frozen=True)
class Refusal:
    """The collection has assets of the handler's kind, and the reason no provider fits.

    ``transient`` marks a read that failed for a reason the next ingest may
    not meet, such as a server that does not answer.
    """

    reason: str
    transient: bool = False


def is_transient(error: BaseException) -> bool:
    """Whether a read failed for a reason other than a missing or an oversized object."""
    lasting = isinstance(error, (FileNotFoundError, DocumentTooLargeError))
    return isinstance(error, (OSError, BaseError)) and not lasting


def describe_read_error(error: Exception) -> str:
    """Why a document could not be read, in one line for a summary."""
    if isinstance(error, FileNotFoundError):
        return "it does not exist"
    text = str(error).strip()
    return (text.splitlines()[0] if text else type(error).__name__)[:200]


class Handler(Protocol):
    """Reads one kind of asset; ``None`` when the collection has none of that kind."""

    async def __call__(
        self, collection: Collection, ingest_options: IngestOptions
    ) -> ProviderMatch | Refusal | None:
        """The provider for ``collection``, or the reason there is none."""
        ...
