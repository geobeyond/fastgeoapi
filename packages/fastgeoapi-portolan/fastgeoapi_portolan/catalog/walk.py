"""The walk of a catalog, as generators that do no I/O.

Each generator yields the locations it needs next and receives, for each
of them, the bytes or the ``OSError`` the transport raised. The driver
does the reading and decides how many documents to fetch at once.

Only ``child`` links are followed, and only from catalogs: collections do
not nest. A Portolan catalog keeps its translations in trees the root
links with ``rel: alternate``, and a link into one of them is not
followed, or every collection would come in twice. Items are read only
when asked for.
"""

from __future__ import annotations

import json
from collections.abc import Generator, Mapping
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from fastgeoapi_portolan.catalog.locations import is_url, resolve, root_document
from fastgeoapi_portolan.catalog.protocols import SchemaValidator
from fastgeoapi_portolan.catalog.results import (
    Catalog,
    Collection,
    Items,
    Nonconforming,
    Skipped,
)
from fastgeoapi_portolan.catalog.types import CollectionDocument, ItemDocument

PORTOLAN_SCHEMAS = "https://schemas.portolan-sdi.org/portolan/"
NO_PORTOLAN_SCHEMA = "the catalog declares no Portolan schema: read as plain STAC"

T = TypeVar("T")
Replies = Mapping[str, bytes | OSError]
Steps = Generator[tuple[str, ...], Replies, T]


class _UnusableError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _why(error: OSError) -> str:
    if isinstance(error, FileNotFoundError):
        return "the document could not be read: it does not exist"
    text = str(error).strip()
    first_line = text.splitlines()[0] if text else type(error).__name__
    return f"the document could not be read: {first_line[:200]}"


def _document(reply: bytes | OSError) -> dict[str, Any]:
    if isinstance(reply, OSError):
        raise _UnusableError(_why(reply))
    try:
        document = json.loads(reply)
    except ValueError:
        raise _UnusableError("the document is not JSON") from None
    if not isinstance(document, dict):
        raise _UnusableError("the document is not a JSON object")
    return document


def _required(href: str, reply: bytes | OSError) -> dict[str, Any]:
    """The document at ``href``, which the walk cannot go without."""
    if isinstance(reply, OSError):
        raise reply
    try:
        return _document(reply)
    except _UnusableError as error:
        raise ValueError(f"{href}: {error.reason}") from None


def _profile(document: Mapping[str, Any]) -> str | None:
    extensions = document.get("stac_extensions")
    if not isinstance(extensions, list):
        return None
    return next(
        (uri for uri in extensions if isinstance(uri, str) and uri.startswith(PORTOLAN_SCHEMAS)),
        None,
    )


def _version(profile: str) -> str:
    return profile[len(PORTOLAN_SCHEMAS) :].split("/", 1)[0]


def _links(
    document: Mapping[str, Any], rel: str, href: str, media_type: str | None = None
) -> list[str]:
    links = document.get("links")
    if not isinstance(links, list):
        return []
    return [
        resolve(href, link["href"])
        for link in links
        if isinstance(link, dict)
        and link.get("rel") == rel
        and (media_type is None or link.get("type") == media_type)
        and isinstance(link.get("href"), str)
        and link["href"]
    ]


def _folder(location: str) -> str:
    return location.rsplit("/", 1)[0] if is_url(location) else str(Path(location).parent)


def _within(location: str, folder: str) -> bool:
    if is_url(location) or is_url(folder):
        return location.startswith(f"{folder.rstrip('/')}/")
    return Path(location).is_relative_to(folder)


class _Walk:
    """One walk of a catalog: the documents seen, and what they held."""

    def __init__(
        self,
        root: str,
        document: Mapping[str, Any],
        only: frozenset[str] | None,
        validator: SchemaValidator | None,
    ) -> None:
        self.root = root
        self.only = only
        self.validator = validator
        self.profile = _profile(document)
        self.seen = {root}
        self.collections: list[Collection] = []
        self.nonconforming: list[Nonconforming] = []
        self.skipped: list[Skipped] = []
        # A dict keeps the warnings in order, each one once.
        self.warnings: dict[str, None] = {}
        if self.profile is None:
            self.warn(NO_PORTOLAN_SCHEMA)
        # A tree in the root's own folder, or above it, cannot be told apart
        # by its folder: only its root document is left out.
        self.trees: list[tuple[str, str | None]] = []
        for tree in _links(document, "alternate", root, "application/json"):
            folder = _folder(tree)
            self.trees.append((tree, None if _within(root, folder) else folder))

    def warn(self, text: str) -> None:
        self.warnings[text] = None

    def visit(self, href: str, document: dict[str, Any]) -> list[str]:
        """Take in ``document``; return the children to read next."""
        kind = document.get("type")
        if kind == "Collection":
            self.collection(href, document)
            return []
        if kind != "Catalog":
            self.skipped.append(Skipped(href, "the document is neither a catalog nor a collection"))
            return []
        self.declared(href, document)
        self.check(href, "Catalog", document)
        return [child for child in _links(document, "child", href) if self.unseen(child)]

    def collection(self, href: str, document: dict[str, Any]) -> None:
        identifier = document.get("id")
        if not isinstance(identifier, str) or not identifier:
            identifier = None
        if self.only is not None and identifier not in self.only:
            return
        if _links(document, "child", href):
            self.warn(f"{href} links a child from a collection; collections do not nest")
        self.declared(href, document)
        if not self.check(href, "Collection", document):
            return
        if identifier is None:
            self.skipped.append(Skipped(href, "the collection has no id"))
            return
        items = tuple(item for item in _links(document, "item", href) if not self.translated(item))
        self.collections.append(
            Collection(
                id=identifier,
                href=href,
                document=cast(CollectionDocument, document),
                item_hrefs=items,
                profile=_profile(document) or self.profile,
            )
        )

    def declared(self, href: str, document: Mapping[str, Any]) -> None:
        own = _profile(document)
        if own and self.profile and _version(own) != _version(self.profile):
            self.warn(
                f"{href} declares Portolan {_version(own)}, "
                f"the catalog declares {_version(self.profile)}"
            )

    def check(
        self, href: str, kind: Literal["Catalog", "Collection"], document: dict[str, Any]
    ) -> bool:
        """Whether ``document`` passes the validator; a rejected one is kept."""
        if self.validator is None:
            return True
        validation = self.validator.validate(document, root_profile=self.profile)
        for schema in validation.unverified:
            self.warn(f"{schema} is not bundled: not checked")
        if validation.findings:
            self.nonconforming.append(Nonconforming(href, kind, document, validation.findings))
            return False
        return True

    def unseen(self, href: str) -> bool:
        if href in self.seen:
            return False
        self.seen.add(href)
        return not self.translated(href)

    def translated(self, href: str) -> bool:
        if any(href == tree or (folder and _within(href, folder)) for tree, folder in self.trees):
            self.warn(f"{href} is in a translation tree: not followed")
            return True
        return False

    def result(self) -> Catalog:
        return Catalog(
            root=self.root,
            portolan_schema=self.profile,
            collections=tuple(self.collections),
            nonconforming=tuple(self.nonconforming),
            skipped=tuple(self.skipped),
            warnings=tuple(self.warnings),
            validated=self.validator is not None,
        )


def walk(
    location: str,
    *,
    only: frozenset[str] | None = None,
    validator: SchemaValidator | None = None,
) -> Steps[Catalog]:
    """Walk the catalog at ``location`` down to its collections.

    ``location`` is the root ``catalog.json`` or the folder that holds it.
    ``only`` keeps the collections with those ids. A child that cannot be
    read, or is not JSON, is skipped with the reason; a root that cannot
    be read raises. With a validator, every catalog and collection is
    checked, and a rejected one is kept apart while the walk goes on below
    it.
    """
    root = root_document(location)
    replies = yield (root,)
    document = _required(root, replies[root])
    state = _Walk(root, document, only, validator)
    pending = state.visit(root, document)
    while pending:
        batch = tuple(pending)
        replies = yield batch
        pending = []
        for href in batch:
            try:
                child = _document(replies[href])
            except _UnusableError as error:
                state.skipped.append(Skipped(href, error.reason))
                continue
            pending.extend(state.visit(href, child))
    # The driver takes the result from StopIteration.
    return state.result()  # ruff: ignore[return-in-generator]


def walk_items(collection: Collection, *, validator: SchemaValidator | None = None) -> Steps[Items]:
    """Read the items ``collection`` links, held to the collection's profile.

    An item that cannot be read raises: a collection served without one of
    its parts would be silently incomplete.
    """
    if not collection.item_hrefs:
        return Items((), ())
    replies = yield collection.item_hrefs
    items: list[ItemDocument] = []
    nonconforming: list[Nonconforming] = []
    for href in collection.item_hrefs:
        document = _required(href, replies[href])
        if validator is not None:
            validation = validator.validate(document, root_profile=collection.profile)
            if validation.findings:
                nonconforming.append(Nonconforming(href, "Item", document, validation.findings))
                continue
        items.append(cast(ItemDocument, document))
    return Items(tuple(items), tuple(nonconforming))  # ruff: ignore[return-in-generator]
