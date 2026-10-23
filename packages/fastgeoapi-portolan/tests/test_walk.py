"""The rules of the walk, read through the reference transport on the kit's catalogs."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from fastgeoapi_portolan.catalog.drivers import (
    read_catalog,
    read_catalog_async,
    read_items,
    to_thread,
)
from fastgeoapi_portolan.catalog.results import Finding, Validation
from fastgeoapi_portolan.catalog.testing import (
    PORTOLAN,
    check_async_transport,
    check_transport,
    write_fixtures,
)
from fastgeoapi_portolan.catalog.urllib_transport import UrllibTransport
from fastgeoapi_portolan.catalog.walk import NO_PORTOLAN_SCHEMA

TRANSPORT = UrllibTransport()
OLDER_PORTOLAN = "https://schemas.portolan-sdi.org/portolan/v0.1.1/schema.json"


class FakeValidator:
    """Rejects the documents whose id starts with ``bad-``, and records what it is given."""

    def __init__(self, unverified: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[str | None, str | None]] = []
        self.unverified = unverified

    def validate(self, document, *, root_profile):
        self.calls.append((document.get("id"), root_profile))
        rejected = str(document.get("id", "")).startswith("bad-")
        findings = (Finding("/id", "rejected by the fake", "fake"),) if rejected else ()
        return Validation(findings, self.unverified)


def _rewrite(path: Path, change) -> None:
    document = json.loads(path.read_text())
    change(document)
    path.write_text(json.dumps(document))


def _ids(catalog) -> list[str]:
    return sorted(collection.id for collection in catalog.collections)


@pytest.fixture
def fixtures(tmp_path):
    return write_fixtures(tmp_path)


def test_only_child_links_are_followed(fixtures):
    catalog = read_catalog(str(fixtures.nested), TRANSPORT)

    assert _ids(catalog) == ["rivers", "roads"]
    assert catalog.root == str(fixtures.nested.resolve())
    assert catalog.portolan_schema == PORTOLAN


def test_a_child_link_inside_a_collection_is_not_followed(fixtures):
    roads = fixtures.nested.parent / "data" / "roads" / "collection.json"
    _rewrite(
        roads,
        lambda document: document["links"].append(
            {"rel": "child", "href": "../deeper/rivers/collection.json", "type": "application/json"}
        ),
    )

    catalog = read_catalog(str(fixtures.nested), TRANSPORT)

    assert _ids(catalog) == ["rivers", "roads"]
    assert f"{roads} links a child from a collection; collections do not nest" in catalog.warnings


def test_a_child_link_into_a_translation_tree_is_not_followed(fixtures):
    catalog = read_catalog(str(fixtures.translated), TRANSPORT)
    strade = fixtures.translated.parent / "it" / "strade" / "collection.json"

    assert _ids(catalog) == ["roads"]
    assert f"{strade} is in a translation tree: not followed" in catalog.warnings


def test_a_child_link_back_to_the_root_is_followed_once(fixtures):
    found = {}

    # A walk that loops never returns; a thread can be left behind.
    walk = threading.Thread(
        target=lambda: found.update(catalog=read_catalog(str(fixtures.cycle), TRANSPORT)),
        daemon=True,
    )
    walk.start()
    walk.join(timeout=5)

    assert not walk.is_alive(), "the walk did not end"
    assert _ids(found["catalog"]) == ["roads"]


def test_a_missing_child_is_skipped_with_the_reason(fixtures):
    catalog = read_catalog(str(fixtures.missing_child), TRANSPORT)

    assert _ids(catalog) == ["roads"]
    (skipped,) = catalog.skipped
    assert skipped.collection.endswith("gone/collection.json")
    assert skipped.reason == "the document could not be read: it does not exist"


def test_a_document_that_is_not_json_is_skipped(fixtures):
    catalog = read_catalog(str(fixtures.not_json), TRANSPORT)

    assert _ids(catalog) == ["roads"]
    assert [skipped.reason for skipped in catalog.skipped] == ["the document is not JSON"]


def test_an_unreadable_root_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_catalog(str(tmp_path / "nowhere" / "catalog.json"), TRANSPORT)


def test_only_selects_collections_by_id(fixtures):
    catalog = read_catalog(str(fixtures.nested), TRANSPORT, only=frozenset({"roads"}))

    assert _ids(catalog) == ["roads"]


def test_items_are_read_only_when_asked(fixtures):
    (buildings,) = read_catalog(str(fixtures.partitioned), TRANSPORT).collections

    items = read_items(buildings, TRANSPORT)

    assert len(buildings.item_hrefs) == 3
    assert [item["id"] for item in items.items] == ["part-0", "part-1", "part-2"]
    assert items.nonconforming == ()


def test_a_catalog_without_the_portolan_schema_is_read_with_a_warning(fixtures):
    catalog = read_catalog(str(fixtures.plain_stac), TRANSPORT)

    assert catalog.portolan_schema is None
    assert _ids(catalog) == ["roads"]
    assert catalog.warnings == (NO_PORTOLAN_SCHEMA,)


def test_without_a_validator_nothing_is_verified(fixtures):
    catalog = read_catalog(str(fixtures.nonconforming), TRANSPORT)

    assert catalog.validated is False
    assert _ids(catalog) == ["untitled"]
    assert catalog.nonconforming == ()


def test_a_document_the_validator_rejects_is_kept_as_nonconforming(fixtures):
    base = fixtures.nested.parent
    _rewrite(base / "data" / "catalog.json", lambda document: document.update(id="bad-data"))
    _rewrite(base / "data" / "roads" / "collection.json", lambda d: d.update(id="bad-roads"))

    catalog = read_catalog(str(fixtures.nested), TRANSPORT, validator=FakeValidator())

    assert catalog.validated is True
    assert {(entry.kind, entry.document["id"]) for entry in catalog.nonconforming} == {
        ("Catalog", "bad-data"),
        ("Collection", "bad-roads"),
    }
    # The walk goes on below a catalog it rejects.
    assert _ids(catalog) == ["rivers"]


def test_the_root_profile_reaches_the_validator(fixtures):
    validator = FakeValidator()

    read_catalog(str(fixtures.nested), TRANSPORT, validator=validator)

    assert {root_profile for _, root_profile in validator.calls} == {PORTOLAN}
    assert len(validator.calls) == 5


def test_a_collection_with_another_profile_version_is_warned(fixtures):
    roads = fixtures.nested.parent / "data" / "roads" / "collection.json"
    _rewrite(roads, lambda d: d.update(stac_extensions=[OLDER_PORTOLAN, *d["stac_extensions"][1:]]))

    catalog = read_catalog(str(fixtures.nested), TRANSPORT)

    assert f"{roads} declares Portolan v0.1.1, the catalog declares v0.2.0" in catalog.warnings
    assert {c.id: c.profile for c in catalog.collections}["roads"] == OLDER_PORTOLAN


def test_unverified_schemas_are_warned_once(fixtures):
    unknown = "https://stac-extensions.github.io/table/v9.9.9/schema.json"

    catalog = read_catalog(
        str(fixtures.nested), TRANSPORT, validator=FakeValidator(unverified=(unknown,))
    )

    assert catalog.warnings.count(f"{unknown} is not bundled: not checked") == 1


def test_the_kit_passes_with_the_reference_transport(tmp_path):
    check_transport(UrllibTransport(), tmp_path)


@pytest.mark.asyncio
async def test_the_kit_passes_through_a_thread(tmp_path):
    await check_async_transport(to_thread(UrllibTransport()), tmp_path)


class FailingTransport:
    """The reference transport, with one location that fails with ``error``."""

    def __init__(self, failing: str, error: OSError) -> None:
        self.failing = failing
        self.error = error

    def read(self, location: str) -> bytes:
        if location == self.failing:
            raise self.error
        return TRANSPORT.read(location)


class CountingTransport:
    """An async transport that records how many reads were in flight at most."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.most = 0

    async def read(self, location: str) -> bytes:
        self.in_flight += 1
        self.most = max(self.most, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return TRANSPORT.read(location)


def test_a_document_that_is_not_a_json_object_is_skipped(fixtures):
    (fixtures.nested.parent / "data" / "roads" / "collection.json").write_text("[]")

    catalog = read_catalog(str(fixtures.nested), TRANSPORT)

    assert _ids(catalog) == ["rivers"]
    assert [skipped.reason for skipped in catalog.skipped] == ["the document is not a JSON object"]


def test_a_child_that_is_neither_a_catalog_nor_a_collection_is_skipped(fixtures):
    roads = fixtures.nested.parent / "data" / "roads" / "collection.json"
    _rewrite(roads, lambda document: document.update(type="Feature"))

    catalog = read_catalog(str(fixtures.nested), TRANSPORT)

    assert _ids(catalog) == ["rivers"]
    assert catalog.skipped[0].reason == "the document is neither a catalog nor a collection"


def test_a_collection_without_an_id_is_skipped(fixtures):
    roads = fixtures.nested.parent / "data" / "roads" / "collection.json"
    _rewrite(roads, lambda document: document.pop("id"))

    catalog = read_catalog(str(fixtures.nested), TRANSPORT)

    assert _ids(catalog) == ["rivers"]
    assert [(entry.collection, entry.reason) for entry in catalog.skipped] == [
        (str(roads), "the collection has no id")
    ]


def test_a_root_that_is_not_json_raises(fixtures):
    fixtures.nested.write_text("not JSON")

    with pytest.raises(ValueError, match="the document is not JSON"):
        read_catalog(str(fixtures.nested), TRANSPORT)


def test_another_read_failure_gives_the_first_line_of_the_error(fixtures):
    roads = fixtures.nested.parent / "data" / "roads" / "collection.json"
    transport = FailingTransport(str(roads), OSError(f"{'x' * 300}\nsecond line"))

    catalog = read_catalog(str(fixtures.nested), transport)

    assert [skipped.reason for skipped in catalog.skipped] == [
        f"the document could not be read: {'x' * 200}"
    ]


def test_a_translation_beside_the_root_leaves_out_only_its_root(fixtures):
    base = fixtures.nested.parent
    (base / "catalog-it.json").write_text(json.dumps({"type": "Catalog", "id": "it", "links": []}))
    tree = {"rel": "alternate", "href": "./catalog-it.json", "type": "application/json"}
    child = {"rel": "child", "href": "./catalog-it.json", "type": "application/json"}
    _rewrite(fixtures.nested, lambda document: document["links"].extend([tree, child]))

    catalog = read_catalog(str(fixtures.nested), TRANSPORT)

    assert _ids(catalog) == ["rivers", "roads"]
    assert f"{base / 'catalog-it.json'} is in a translation tree: not followed" in catalog.warnings


def test_an_item_link_into_a_translation_tree_is_not_followed(fixtures):
    roads = fixtures.translated.parent / "roads" / "collection.json"
    strada = fixtures.translated.parent / "it" / "strade" / "strada.json"
    link = {"rel": "item", "href": "../it/strade/strada.json", "type": "application/geo+json"}
    _rewrite(roads, lambda document: document["links"].append(link))

    catalog = read_catalog(str(fixtures.translated), TRANSPORT)

    assert catalog.collections[0].item_hrefs == ()
    assert f"{strada} is in a translation tree: not followed" in catalog.warnings


def test_an_item_that_cannot_be_read_raises(fixtures):
    (buildings,) = read_catalog(str(fixtures.partitioned), TRANSPORT).collections
    Path(buildings.item_hrefs[1]).unlink()

    with pytest.raises(FileNotFoundError):
        read_items(buildings, TRANSPORT)


def test_an_item_the_validator_rejects_is_kept_as_nonconforming(fixtures):
    (buildings,) = read_catalog(str(fixtures.partitioned), TRANSPORT).collections
    _rewrite(Path(buildings.item_hrefs[1]), lambda document: document.update(id="bad-part-1"))
    validator = FakeValidator()

    items = read_items(buildings, TRANSPORT, validator=validator)

    assert [item["id"] for item in items.items] == ["part-0", "part-2"]
    assert [(entry.kind, entry.document["id"]) for entry in items.nonconforming] == [
        ("Item", "bad-part-1")
    ]
    assert {root_profile for _, root_profile in validator.calls} == {buildings.profile}


@pytest.mark.asyncio
async def test_the_async_driver_keeps_to_its_concurrency(fixtures):
    transport = CountingTransport()

    catalog = await read_catalog_async(str(fixtures.nested), transport, concurrency=1)

    assert _ids(catalog) == ["rivers", "roads"]
    assert transport.most == 1


@pytest.fixture
def served_fixtures(fixtures):
    """The kit's catalogs over HTTP on loopback."""
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    base = fixtures.nested.parent.parent
    handler = partial(SimpleHTTPRequestHandler, directory=str(base))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield fixtures, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_a_remote_catalog_cannot_link_a_local_file(served_fixtures):
    fixtures, url = served_fixtures
    local_collection = fixtures.translated.parent / "roads" / "collection.json"
    local_item = fixtures.partitioned.parent / "buildings" / "part=0" / "part-0.json"
    child = {"rel": "child", "href": local_collection.as_uri(), "type": "application/json"}
    item = {"rel": "item", "href": local_item.as_uri(), "type": "application/geo+json"}
    _rewrite(fixtures.nested, lambda document: document["links"].append(child))
    roads = fixtures.nested.parent / "data" / "roads" / "collection.json"
    _rewrite(roads, lambda document: document["links"].append(item))

    catalog = read_catalog(f"{url}/nested/catalog.json", TRANSPORT)

    assert _ids(catalog) == ["rivers", "roads"]
    assert {c.id: c.item_hrefs for c in catalog.collections}["roads"] == ()
    for href in (local_collection.as_uri(), local_item.as_uri()):
        warning = f"{href} is on the local disk, linked from a remote catalog: not followed"
        assert warning in catalog.warnings


def test_a_local_catalog_still_follows_its_local_links(fixtures):
    local_collection = fixtures.translated.parent / "roads" / "collection.json"
    child = {"rel": "child", "href": local_collection.as_uri(), "type": "application/json"}
    _rewrite(fixtures.nested, lambda document: document["links"].append(child))

    catalog = read_catalog(str(fixtures.nested), TRANSPORT)

    assert local_collection.as_uri() in [collection.href for collection in catalog.collections]
