"""What a handler is: it turns one kind of asset in a collection into a fastgeoapi provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastgeoapi_portolan.reader import Collection


@dataclass(frozen=True)
class Overrides:
    """What the command line says in place of the catalog.

    ``id_fields`` and ``geometry_columns`` map a collection id to a column.
    """

    store_options: Mapping[str, Any] = field(default_factory=dict)
    id_fields: Mapping[str, str] = field(default_factory=dict)
    geometry_columns: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Provided:
    """A provider for the resource, and where each of its values came from."""

    provider: dict[str, Any]
    choices: tuple[str, ...]


@dataclass(frozen=True)
class Refused:
    """The collection has assets of the handler's kind, and the reason no provider fits."""

    reason: str


def unreadable(error: Exception) -> str:
    """Why a document could not be read, in one line for a summary."""
    if isinstance(error, FileNotFoundError):
        return "it does not exist"
    text = str(error).strip()
    return (text.splitlines()[0] if text else type(error).__name__)[:200]


class Handler(Protocol):
    """Reads one kind of asset; ``None`` when the collection has none of that kind."""

    async def __call__(
        self, collection: Collection, overrides: Overrides
    ) -> Provided | Refused | None:
        """The provider for ``collection``, or the reason there is none."""
        ...
