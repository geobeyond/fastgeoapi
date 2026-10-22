"""GeoParquet data as a feature provider of fastgeoapi.

The data is, in this order: the collection's ``partition:glob``; its
``data`` asset, read through the asset's ``s3`` alternate when it has one;
a glob over the folder that holds the data of its items. An https URL of
an S3 bucket becomes an ``s3://`` URL, so DuckDB can expand a glob in it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from fastgeoapi_portolan.catalog.locations import is_url, resolve
from fastgeoapi_portolan.handlers import Overrides, Provided, Refused
from fastgeoapi_portolan.reader import Collection, read_items

PROVIDER = "app.provider.geoparquet.GeoParquetProvider"
PARQUET = "application/vnd.apache.parquet"
ID_NAMES = ("id", "fid", "objectid", "gid")
GEOMETRY_NAMES = ("geometry", "geom", "wkb_geometry")

_REGION = r"(?P<region>[a-z]{2}(?:-[a-z]+)+-\d+)"
_VIRTUAL_HOSTED = re.compile(
    rf"^https://(?P<bucket>[^/]+?)\.s3[.-]{_REGION}\.amazonaws\.com/(?P<key>.+)$"
)
_PATH_STYLE = re.compile(
    rf"^https://s3[.-]{_REGION}\.amazonaws\.com/(?P<bucket>[^/]+)/(?P<key>.+)$"
)


def s3_from_https(url: str) -> tuple[str, dict[str, Any]] | None:
    """The ``s3://`` URL and the store options for an https URL of an S3 bucket.

    Both the virtual-hosted and the path-style forms carry the region. The
    options read the bucket without signing: a catalog that links its data
    over https expects anyone to read it.
    """
    found = _VIRTUAL_HOSTED.match(url) or _PATH_STYLE.match(url)
    if found is None:
        return None
    return (
        f"s3://{found['bucket']}/{found['key']}",
        {"region": found["region"], "skip_signature": True},
    )


def _is_parquet_data(asset: Any) -> bool:
    if not isinstance(asset, Mapping) or not isinstance(asset.get("href"), str):
        return False
    media_type = str(asset.get("type", "")).split(";", 1)[0].strip()
    roles = asset.get("roles")
    return media_type == PARQUET and isinstance(roles, list) and "data" in roles


def _data_asset(document: Mapping[str, Any]) -> Mapping[str, Any] | None:
    assets = document.get("assets")
    if not isinstance(assets, Mapping):
        return None
    return next(
        (asset for asset in assets.values() if _is_parquet_data(asset)), None
    )


def _folder(location: str) -> str:
    return (
        location.rsplit("/", 1)[0]
        if is_url(location)
        else str(Path(location).parent)
    )


def _columns(described: Iterable[Mapping[str, Any]]) -> list[str]:
    """The column names that ``table:columns`` lists, in the order first seen."""
    names: dict[str, None] = {}
    for fields in described:
        columns = fields.get("table:columns")
        for column in columns if isinstance(columns, list) else ():
            if isinstance(column, Mapping) and isinstance(
                column.get("name"), str
            ):
                names[column["name"]] = None
    return list(names)


def _by_name(columns: list[str], names: tuple[str, ...]) -> str | None:
    """The column matching the first of ``names`` present, compared without case."""
    lowered = {column.lower(): column for column in reversed(columns)}
    return next((lowered[name] for name in names if name in lowered), None)


def _id_field(
    collection: Collection, columns: list[str], overrides: Overrides
) -> tuple[str, str] | Refused:
    key = collection.document.get("table:primary_key")
    if isinstance(key, list) and len(key) == 1 and isinstance(key[0], str):
        return key[0], "table:primary_key"
    named = _by_name(columns, ID_NAMES)
    if named is not None:
        return named, "column name"
    if collection.id in overrides.id_fields:
        return overrides.id_fields[collection.id], "option"
    # The provider takes a single column.
    composite = isinstance(key, list) and len(key) > 1
    why = (
        f"table:primary_key {key} is composite"
        if composite
        else "no column to use as id"
    )
    return Refused(f"{why}: pass --id-field {collection.id}=<column>")


def _geometry_column(
    collection: Collection, columns: list[str], overrides: Overrides
) -> tuple[str, str] | Refused:
    declared = collection.document.get("table:primary_geometry")
    if isinstance(declared, str) and declared:
        return declared, "table:primary_geometry"
    named = _by_name(columns, GEOMETRY_NAMES)
    if named is not None:
        return named, "column name"
    if collection.id in overrides.geometry_columns:
        return overrides.geometry_columns[collection.id], "option"
    return Refused(
        f"no geometry column: pass --geometry-column {collection.id}=<column>"
    )


def _listed(locations: list[str], limit: int = 3) -> str:
    shown = ", ".join(locations[:limit])
    rest = len(locations) - limit
    return f"{shown} and {rest} more" if rest > 0 else shown


async def geoparquet(
    collection: Collection, overrides: Overrides
) -> Provided | Refused | None:
    """The feature provider for the GeoParquet data of ``collection``.

    The items are read when the data is in them or partitioned. A
    partitioned dataset with an item that does not conform is refused as a
    whole, and the reason names the items.
    """
    document = collection.document
    glob = document.get("partition:glob")
    glob = glob if isinstance(glob, str) and glob else None
    asset = _data_asset(document)
    described: list[Mapping[str, Any]] = [document, *([asset] if asset else [])]
    choices: list[str] = []
    data: str | None = None

    if collection.item_hrefs and (glob or asset is None):
        items = await read_items(collection, overrides.store_options)
        documents = [
            *items.items,
            *(entry.document for entry in items.nonconforming),
        ]
        if glob is None and not any(_data_asset(item) for item in documents):
            return None
        if items.nonconforming:
            rejected = [entry.href for entry in items.nonconforming]
            return Refused(
                f"{len(rejected)} items do not conform: {_listed(rejected)}"
            )
        parts = [
            (href, found)
            for href, item in zip(
                collection.item_hrefs, items.items, strict=True
            )
            if (found := _data_asset(item)) is not None
        ]
        described += [found for _, found in parts]
        described += [item.get("properties") or {} for item in items.items]
        if glob is None:
            folders = sorted(
                {_folder(resolve(href, found["href"])) for href, found in parts}
            )
            if len(folders) > 1:
                return Refused(
                    f"the data of the items is in {len(folders)} folders, a glob takes one: "
                    f"{_listed(folders)}"
                )
            data = f"{folders[0]}/*.parquet"
            choices.append(f"data: glob of {len(parts)} items")

    if glob is not None:
        data = resolve(collection.href, glob)
        choices.append("data: partition:glob")
    elif asset is not None:
        alternate = asset.get("alternate")
        s3 = alternate.get("s3") if isinstance(alternate, Mapping) else None
        if isinstance(s3, Mapping) and str(s3.get("href", "")).startswith(
            "s3://"
        ):
            data = str(s3["href"])
            choices.append("data: s3 alternate")
        else:
            data = resolve(collection.href, asset["href"])
            choices.append("data: collection asset")
    if data is None:
        return None

    store_options: dict[str, Any] = {}
    rewritten = s3_from_https(data)
    if rewritten is not None:
        data, store_options = rewritten
        choices.append("data: s3 URL from the https one")
    store_options.update(overrides.store_options)

    columns = _columns(described)
    id_field = _id_field(collection, columns, overrides)
    if isinstance(id_field, Refused):
        return id_field
    geometry = _geometry_column(collection, columns, overrides)
    if isinstance(geometry, Refused):
        return geometry
    choices.append(f"id_field: {id_field[0]} ({id_field[1]})")
    choices.append(f"geometry_column: {geometry[0]} ({geometry[1]})")

    provider: dict[str, Any] = {
        "type": "feature",
        "name": PROVIDER,
        "data": data,
        "id_field": id_field[0],
        "geometry_column": geometry[0],
    }
    if store_options:
        provider["store_options"] = store_options
    return Provided(provider, tuple(choices))
