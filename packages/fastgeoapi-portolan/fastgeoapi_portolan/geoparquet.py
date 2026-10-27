"""GeoParquet data as a feature provider of fastgeoapi.

The data is, in this order: the collection's ``partition:glob``; its
``data`` asset, read through the asset's ``s3`` alternate when it has one;
a glob over the folder that holds the data of its items. An https URL of
an S3 bucket becomes an ``s3://`` URL, so DuckDB can expand a glob in it.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from fastgeoapi_portolan.catalog.locations import (
    LOCAL_FROM_REMOTE,
    is_local_from_remote,
    is_url,
    resolve,
)
from fastgeoapi_portolan.handlers import (
    IngestOptions,
    ProviderMatch,
    Refusal,
    describe_read_error,
    is_transient,
)
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
# The store options that are also parameters of a DuckDB S3 secret.
_SECRET_OPTIONS = (
    "region",
    "endpoint",
    "url_style",
    "use_ssl",
    "key_id",
    "secret",
    "session_token",
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
    return next((asset for asset in assets.values() if _is_parquet_data(asset)), None)


def _bucket(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0]


def _folder(location: str) -> str:
    return location.rsplit("/", 1)[0] if is_url(location) else str(Path(location).parent)


def _columns(described: Iterable[Mapping[str, Any]]) -> list[str]:
    """The column names that ``table:columns`` lists, in the order first seen."""
    names: dict[str, None] = {}
    for fields in described:
        columns = fields.get("table:columns")
        for column in columns if isinstance(columns, list) else ():
            if isinstance(column, Mapping) and isinstance(column.get("name"), str):
                names[column["name"]] = None
    return list(names)


def _by_name(columns: list[str], names: tuple[str, ...]) -> str | None:
    """The column matching the first of ``names`` present, compared without case."""
    lowered = {column.lower(): column for column in reversed(columns)}
    return next((lowered[name] for name in names if name in lowered), None)


def _id_field(
    collection: Collection, columns: list[str], ingest_options: IngestOptions
) -> tuple[str, str] | Refusal:
    key = collection.document.get("table:primary_key")
    if isinstance(key, list) and len(key) == 1 and isinstance(key[0], str):
        return key[0], "table:primary_key"
    named = _by_name(columns, ID_NAMES)
    if named is not None:
        return named, "column name"
    if collection.id in ingest_options.id_fields:
        return ingest_options.id_fields[collection.id], "option"
    # The provider takes a single column.
    composite = isinstance(key, list) and len(key) > 1
    why = f"table:primary_key {key} is composite" if composite else "no column to use as id"
    return Refusal(f"{why}: pass --id-field {collection.id}=<column>")


def _geometry_column(
    collection: Collection, columns: list[str], ingest_options: IngestOptions
) -> tuple[str, str] | Refusal:
    declared = collection.document.get("table:primary_geometry")
    if isinstance(declared, str) and declared:
        return declared, "table:primary_geometry"
    named = _by_name(columns, GEOMETRY_NAMES)
    if named is not None:
        return named, "column name"
    if collection.id in ingest_options.geometry_columns:
        return ingest_options.geometry_columns[collection.id], "option"
    return Refusal(f"no geometry column: pass --geometry-column {collection.id}=<column>")


def _listed(locations: list[str], limit: int = 3) -> str:
    shown = ", ".join(locations[:limit])
    rest = len(locations) - limit
    return f"{shown} and {rest} more" if rest > 0 else shown


async def geoparquet_provider(
    collection: Collection, ingest_options: IngestOptions
) -> ProviderMatch | Refusal | None:
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
    derived: dict[str, Any] = {}

    if collection.item_hrefs and (glob or asset is None):
        try:
            items = await read_items(
                collection,
                ingest_options.store_options,
                max_items=ingest_options.max_documents,
                max_bytes=ingest_options.max_document_bytes,
            )
        except (OSError, ValueError) as error:
            reason = f"the items could not be read: {describe_read_error(error)}"
            return Refusal(reason, transient=is_transient(error))
        documents = [
            *items.items,
            *(entry.document for entry in items.nonconforming),
        ]
        if glob is None and not any(_data_asset(item) for item in documents):
            return None
        if items.nonconforming:
            rejected = [entry.href for entry in items.nonconforming]
            return Refusal(f"{len(rejected)} items do not conform: {_listed(rejected)}")
        parts = [
            (href, found)
            for href, item in zip(collection.item_hrefs, items.items, strict=True)
            if (found := _data_asset(item)) is not None
        ]
        described += [found for _, found in parts]
        described += [item.get("properties") or {} for item in items.items]
        if glob is None:
            folders = sorted({_folder(resolve(href, found["href"])) for href, found in parts})
            if len(folders) > 1:
                return Refusal(
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
        if isinstance(s3, Mapping) and str(s3.get("href", "")).startswith("s3://"):
            data = str(s3["href"])
            choices.append("data: s3 alternate")
            linked = s3_from_https(resolve(collection.href, asset["href"]))
            # The https URL names the same bucket, so the region is the same,
            # and the catalog expects anyone to read the object.
            if linked is not None and _bucket(linked[0]) == _bucket(data):
                derived = linked[1]
                choices.append("data: s3 options from the https URL")
        else:
            data = resolve(collection.href, asset["href"])
            choices.append("data: collection asset")
    if data is None:
        return None
    if is_local_from_remote(collection.href, data):
        return Refusal(f"the data {data} {LOCAL_FROM_REMOTE}")

    store_options = dict(derived)
    rewritten = s3_from_https(data)
    if rewritten is not None:
        data, store_options = rewritten
        choices.append("data: s3 URL from the https one")
    store_options.update(ingest_options.store_options)

    columns = _columns(described)
    id_field = _id_field(collection, columns, ingest_options)
    if isinstance(id_field, Refusal):
        return id_field
    geometry = _geometry_column(collection, columns, ingest_options)
    if isinstance(geometry, Refusal):
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
    return ProviderMatch(provider, tuple(choices))


def _literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _s3_secret(store_options: Mapping[str, Any]) -> str:
    parameters = ["TYPE s3"]
    parameters += [
        f"{name.upper()} {_literal(store_options[name])}"
        for name in _SECRET_OPTIONS
        if store_options.get(name) is not None
    ]
    if store_options.get("skip_signature") is True:
        # Empty keys stop DuckDB from signing. Without them it signs with the
        # AWS variables of the environment, and a public bucket answers a
        # signed request with 403.
        parameters += ["KEY_ID ''", "SECRET ''"]
    return f"CREATE SECRET ({', '.join(parameters)})"


def _count_duplicate_ids(data: str, column: str, store_options: Mapping[str, Any]) -> int:
    # Here rather than at the top: DuckDB is needed by --check-ids only.
    import duckdb

    connection = duckdb.connect()
    try:
        # DuckDB loads httpfs by itself for a bucket or an http(s) URL.
        if data.startswith("s3://"):
            connection.execute(_s3_secret(store_options))
        identifier = '"' + column.replace('"', '""') + '"'
        # The column is quoted as an identifier and the data is a parameter.
        # ruff: ignore[hardcoded-sql-expression]
        query = (
            f"SELECT count(*) - count(DISTINCT {identifier}) "  # nosec B608
            "FROM read_parquet(?, union_by_name = true)"
        )
        row = connection.execute(query, [data]).fetchone()
        return int(row[0]) if row else 0
    finally:
        connection.close()


async def duplicate_ids(data: str, column: str, store_options: Mapping[str, Any]) -> int:
    """How many rows of ``data`` have no id of their own in ``column``: repeated ids and nulls.

    DuckDB reads that column only, in a thread, since its calls block.
    """
    return await asyncio.to_thread(_count_duplicate_ids, data, column, store_options)
