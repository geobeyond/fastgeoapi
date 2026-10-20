"""The conformance kit: small catalogs on disk, and checks that a transport reads them right.

A transport passes when the walk over it finds, in each catalog, the
collections and the skip reasons the reference transport finds, a root
that does not exist raises ``FileNotFoundError``, and the parts of the
partitioned collection come back in order. Every catalog but
``nonconforming`` and ``not_json`` conforms to Portolan v0.2.0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, cast

from fastgeoapi_portolan.catalog.drivers import (
    read_catalog,
    read_catalog_async,
    read_items,
    read_items_async,
)
from fastgeoapi_portolan.catalog.protocols import AsyncTransport, Transport
from fastgeoapi_portolan.catalog.results import Catalog, Collection, Items

PORTOLAN = "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json"
PARTITION = "https://schemas.portolan-sdi.org/incubating/partition/v1.0.0/schema.json"
ALTERNATE_ASSETS = "https://stac-extensions.github.io/alternate-assets/v1.2.0/schema.json"
TABLE = "https://stac-extensions.github.io/table/v1.2.0/schema.json"

_BBOX = [12.3, 41.8, 12.6, 42.0]
_PARQUET = "application/vnd.apache.parquet"
_MISSING_ROOT = "missing_root"
_PARTS = ("part-0", "part-1", "part-2")


@dataclass(frozen=True)
class Fixtures:
    """The root ``catalog.json`` of each case."""

    nested: Path
    translated: Path
    cycle: Path
    missing_child: Path
    not_json: Path
    nonconforming: Path
    plain_stac: Path
    partitioned: Path
    alternate_assets: Path


# The collections and the skip reasons each case gives.
_EXPECTED: dict[str, tuple[frozenset[str], tuple[str, ...]]] = {
    "nested": (frozenset({"rivers", "roads"}), ()),
    "translated": (frozenset({"roads"}), ()),
    "cycle": (frozenset({"roads"}), ()),
    "missing_child": (
        frozenset({"roads"}),
        ("the document could not be read: it does not exist",),
    ),
    "not_json": (frozenset({"roads"}), ("the document is not JSON",)),
    "nonconforming": (frozenset({"untitled"}), ()),
    "plain_stac": (frozenset({"roads"}), ()),
    "partitioned": (frozenset({"buildings"}), ()),
    "alternate_assets": (frozenset({"bathymetry"}), ()),
}


def _link(rel: str, href: str, title: str | None = None) -> dict[str, str]:
    media_type = "application/geo+json" if rel == "item" else "application/json"
    link = {"rel": rel, "href": href, "type": media_type}
    if title:
        link["title"] = title
    return link


def _title(identifier: str) -> str:
    return identifier.replace("-", " ").capitalize()


def _described(links: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"rel": "agents", "href": "./AGENTS.md", "type": "text/markdown"},
        {"rel": "describedby", "href": "./README.md", "type": "text/markdown"},
        *links,
    ]


def _catalog(
    identifier: str, links: list[dict[str, str]], *, portolan: bool = True
) -> dict[str, Any]:
    return {
        "type": "Catalog",
        "stac_version": "1.1.0",
        "stac_extensions": [PORTOLAN] if portolan else [],
        "id": identifier,
        "title": _title(identifier),
        "description": f"The {identifier} catalog.",
        "links": _described(links),
    }


def _collection(
    identifier: str,
    links: list[dict[str, str]] | None = None,
    *,
    portolan: bool = True,
    extensions: tuple[str, ...] = (),
    assets: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    if assets is None:
        assets = {"data": {"href": f"./{identifier}.parquet", "type": _PARQUET, "roles": ["data"]}}
    return {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": [*([PORTOLAN] if portolan else []), *extensions],
        "id": identifier,
        "title": _title(identifier),
        "description": f"The {identifier} collection.",
        "license": "CC-BY-4.0",
        "extent": {
            "spatial": {"bbox": [_BBOX]},
            "temporal": {"interval": [["2026-01-01T00:00:00Z", None]]},
        },
        "providers": [
            {"name": "Example producer", "roles": ["producer"]},
            {"name": "Example host", "roles": ["host"], "url": "https://example.org"},
        ],
        "links": _described(links or []),
        "assets": assets,
        **extra,
    }


def _item(identifier: str, collection: str) -> dict[str, Any]:
    west, south, east, north = _BBOX
    return {
        "type": "Feature",
        "stac_version": "1.1.0",
        "stac_extensions": [],
        "id": identifier,
        "collection": collection,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [[west, south], [east, south], [east, north], [west, north], [west, south]]
            ],
        },
        "bbox": _BBOX,
        "properties": {"datetime": "2026-01-01T00:00:00Z"},
        "links": [_link("collection", "../collection.json")],
        "assets": {
            "data": {"href": f"./{identifier}.parquet", "type": _PARQUET, "roles": ["data"]}
        },
    }


def _put(
    case: Path, relative: str, document: dict[str, Any], parent: str = "../catalog.json"
) -> None:
    """Write ``document`` at ``relative`` in ``case``, with its root and parent links."""
    depth = relative.count("/")
    structural = [_link("root", f"{'../' * depth}catalog.json" if depth else "./catalog.json")]
    if depth:
        structural.append(_link("parent", parent))
    document = {**document, "links": [*structural, *document["links"]]}
    path = case / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2))
    if document["type"] != "Feature":
        heading = f"# {document.get('title') or document['id']}\n"
        for name in ("AGENTS.md", "README.md"):
            (path.parent / name).write_text(heading)


def _child(identifier: str, href: str) -> dict[str, str]:
    return _link("child", href, _title(identifier))


def _nested(case: Path) -> None:
    _put(case, "catalog.json", _catalog("nested", [_child("data", "./data/catalog.json")]))
    _put(
        case,
        "data/catalog.json",
        _catalog(
            "data",
            [_child("roads", "./roads/collection.json"), _child("deeper", "./deeper/catalog.json")],
        ),
    )
    _put(case, "data/roads/collection.json", _collection("roads"))
    _put(
        case,
        "data/deeper/catalog.json",
        _catalog("deeper", [_child("rivers", "./rivers/collection.json")]),
    )
    _put(case, "data/deeper/rivers/collection.json", _collection("rivers"))


def _translated(case: Path) -> None:
    tree = {
        "rel": "alternate",
        "href": "./it/catalog.json",
        "type": "application/json",
        "hreflang": "it",
        "title": "Italiano",
    }
    links = [
        _child("roads", "./roads/collection.json"),
        # A link into the translation: the walk leaves it out.
        _child("strade", "./it/strade/collection.json"),
        tree,
    ]
    _put(case, "catalog.json", _catalog("translated", links))
    _put(case, "roads/collection.json", _collection("roads"))
    _put(
        case,
        "it/catalog.json",
        _catalog("tradotto", [_child("strade", "./strade/collection.json")]),
    )
    _put(case, "it/strade/collection.json", _collection("strade"))


def _cycle(case: Path) -> None:
    _put(case, "catalog.json", _catalog("cycle", [_child("data", "./data/catalog.json")]))
    links = [_child("roads", "./roads/collection.json"), _child("cycle", "../catalog.json")]
    _put(case, "data/catalog.json", _catalog("data", links))
    _put(case, "data/roads/collection.json", _collection("roads"))


def _missing_child(case: Path) -> None:
    links = [_child("roads", "./roads/collection.json"), _child("gone", "./gone/collection.json")]
    _put(case, "catalog.json", _catalog("missing-child", links))
    _put(case, "roads/collection.json", _collection("roads"))


def _not_json(case: Path) -> None:
    links = [
        _child("roads", "./roads/collection.json"),
        _child("broken", "./broken/collection.json"),
    ]
    _put(case, "catalog.json", _catalog("not-json", links))
    _put(case, "roads/collection.json", _collection("roads"))
    (case / "broken").mkdir()
    (case / "broken" / "collection.json").write_text("this is not JSON\n")


def _nonconforming(case: Path) -> None:
    _put(
        case,
        "catalog.json",
        _catalog("nonconforming", [_child("untitled", "./untitled/collection.json")]),
    )
    untitled = _collection("untitled")
    del untitled["title"]
    _put(case, "untitled/collection.json", untitled)


def _plain_stac(case: Path) -> None:
    root = _catalog("plain-stac", [_child("roads", "./roads/collection.json")], portolan=False)
    _put(case, "catalog.json", root)
    _put(case, "roads/collection.json", _collection("roads", portolan=False))


def _partitioned(case: Path) -> None:
    _put(
        case,
        "catalog.json",
        _catalog("partitioned", [_child("buildings", "./buildings/collection.json")]),
    )
    folders = [f"part={number}" for number in range(len(_PARTS))]
    items = [
        _link("item", f"./{folder}/{part}.json", _title(part))
        for folder, part in zip(folders, _PARTS, strict=True)
    ]
    buildings = _collection(
        "buildings",
        items,
        extensions=(PARTITION,),
        assets={},
        **{
            "partition:scheme": "hive",
            "partition:keys": [{"name": "part", "type": "int32"}],
            "partition:glob": "part=*/*.parquet",
            "partition:file_count": len(_PARTS),
        },
    )
    _put(case, "buildings/collection.json", buildings)
    for folder, part in zip(folders, _PARTS, strict=True):
        _put(
            case, f"buildings/{folder}/{part}.json", _item(part, "buildings"), "../collection.json"
        )


def _alternate_assets(case: Path) -> None:
    _put(
        case,
        "catalog.json",
        _catalog("alternate-assets", [_child("bathymetry", "./bathymetry/collection.json")]),
    )
    data = {
        "href": "https://example-bucket.s3.us-west-2.amazonaws.com/bathymetry/part-0.parquet",
        "type": _PARQUET,
        "roles": ["data"],
        "alternate": {"s3": {"href": "s3://example-bucket/bathymetry/part-0.parquet"}},
    }
    bathymetry = _collection(
        "bathymetry",
        extensions=(TABLE, ALTERNATE_ASSETS),
        assets={"data": data},
        **{
            "table:columns": [
                {"name": "id", "type": "string"},
                {"name": "geometry", "type": "binary"},
            ],
            "table:primary_geometry": "geometry",
        },
    )
    _put(case, "bathymetry/collection.json", bathymetry)


_WRITERS = {
    "nested": _nested,
    "translated": _translated,
    "cycle": _cycle,
    "missing_child": _missing_child,
    "not_json": _not_json,
    "nonconforming": _nonconforming,
    "plain_stac": _plain_stac,
    "partitioned": _partitioned,
    "alternate_assets": _alternate_assets,
}


def write_fixtures(root: Path) -> Fixtures:
    """Write one catalog per case in a folder of ``root`` named after it."""
    root = root.resolve()
    for case, write in _WRITERS.items():
        write(root / case)
    return Fixtures(**{case: root / case / "catalog.json" for case in _WRITERS})


def _locations(fixtures: Fixtures, root: Path) -> dict[str, str]:
    locations = {field.name: str(getattr(fixtures, field.name)) for field in fields(fixtures)}
    locations[_MISSING_ROOT] = str(root.resolve() / _MISSING_ROOT / "catalog.json")
    return locations


def _expect(case: str, condition: bool, what: str) -> None:
    if not condition:
        raise AssertionError(f"{case}: {what}")


def _check(outcomes: dict[str, Catalog | BaseException]) -> Collection:
    """Compare each walk with what the case expects; return the partitioned collection."""
    for case, (identifiers, reasons) in _EXPECTED.items():
        outcome = outcomes[case]
        if isinstance(outcome, BaseException):
            raise AssertionError(f"{case}: the walk raised {outcome!r}") from outcome
        found = frozenset(collection.id for collection in outcome.collections)
        _expect(
            case,
            found == identifiers,
            f"collections {sorted(found)}, expected {sorted(identifiers)}",
        )
        skipped = tuple(entry.reason for entry in outcome.skipped)
        _expect(case, skipped == reasons, f"skipped {skipped}, expected {reasons}")
        schema = None if case == "plain_stac" else PORTOLAN
        _expect(
            case,
            outcome.portolan_schema == schema,
            f"profile {outcome.portolan_schema}, expected {schema}",
        )
    missing = outcomes[_MISSING_ROOT]
    _expect(
        _MISSING_ROOT,
        isinstance(missing, FileNotFoundError),
        f"a root that does not exist gave {missing!r}, expected FileNotFoundError",
    )
    # The loop above raised for any walk that did not return a catalog.
    return cast(Catalog, outcomes["partitioned"]).collections[0]


def _check_items(outcome: Items | BaseException) -> None:
    if isinstance(outcome, BaseException):
        raise AssertionError(f"partitioned: reading the items raised {outcome!r}") from outcome
    found = tuple(item["id"] for item in outcome.items)
    _expect("partitioned", found == _PARTS, f"items {found}, expected {_PARTS}")


def check_transport(transport: Transport, root: Path) -> None:
    """Read every case under ``root`` through ``transport``.

    Raises ``AssertionError`` naming the first case that differs.
    """
    fixtures = write_fixtures(root)
    outcomes: dict[str, Catalog | BaseException] = {}
    for case, location in _locations(fixtures, root).items():
        try:
            outcomes[case] = read_catalog(location, transport)
        except Exception as error:
            outcomes[case] = error
    buildings = _check(outcomes)
    try:
        items: Items | BaseException = read_items(buildings, transport)
    except Exception as error:
        items = error
    _check_items(items)


async def check_async_transport(transport: AsyncTransport, root: Path) -> None:
    """As :func:`check_transport`, through the async driver."""
    fixtures = write_fixtures(root)
    outcomes: dict[str, Catalog | BaseException] = {}
    for case, location in _locations(fixtures, root).items():
        try:
            outcomes[case] = await read_catalog_async(location, transport)
        except Exception as error:
            outcomes[case] = error
    buildings = _check(outcomes)
    try:
        items: Items | BaseException = await read_items_async(buildings, transport)
    except Exception as error:
        items = error
    _check_items(items)
