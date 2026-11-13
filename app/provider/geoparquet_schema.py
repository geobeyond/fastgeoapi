"""The schema of a GeoParquet dataset on an object store, read once per version of its objects.

On a slow route to the store, DuckDB's own reader took minutes to describe
a bucket dataset that the store's client described in seconds (140 s
against 4 s for one 578 MB Overture file), and every boot and reload
describes the dataset again. Here the store's client lists the objects and
reads their footers, and the schema is kept on disk under the objects'
ETags, so an unchanged dataset is not described again.

The store's client takes an S3 endpoint from the process environment,
even over the one a dataset names, once it builds a store for a bucket.
When the environment names one, or when anything on this path fails, the
caller describes the dataset with DuckDB as before: its secret is scoped
to the dataset.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from app.config.logging import create_logger
from app.provider.duckdb_ import connect, protocol_for
from app.provider.storage import load_store, split_source
from app.provider.storage.cache import default_cache_base_dir, digest

logger = create_logger("app.provider.geoparquet_schema")

_ENVIRONMENT_ENDPOINTS = ("AWS_ENDPOINT_URL_S3", "AWS_ENDPOINT_URL")


def schema_cache_dir() -> Path | None:
    """Where schemas are kept: ``schemas`` under fastgeoapi's cache root, or nowhere."""
    base = default_cache_base_dir()
    return None if base is None else base / "schemas"


def remote_schema(
    data: str, *, store_options: dict | None, cache_dir: Path | None
) -> dict[str, str] | None:
    """Column name → DuckDB type for ``data`` on a store, or None to leave it to DuckDB."""
    options = dict(store_options or {})
    if protocol_for(data) == "s3" and any(os.environ.get(name) for name in _ENVIRONMENT_ENDPOINTS):
        return None
    try:
        versions, urls = _objects(data, options)
    except Exception as error:
        logger.warning(f"cannot list {data} through the store ({error}); DuckDB describes it")
        return None
    entry = _entry_path(data, options, cache_dir)
    cached = _read_entry(entry)
    if cached is not None and cached.get("versions") == versions:
        return cached["types"]
    try:
        types = _describe(data, options, urls)
    except Exception as error:
        logger.warning(f"cannot describe {data} through the store ({error}); DuckDB describes it")
        return None
    if entry is not None and None not in versions.values():
        _write_entry(entry, {"source": data, "versions": versions, "types": types})
    return types


def _objects(data: str, options: dict) -> tuple[dict[str, str | None], list[str]]:
    """The parquet objects of ``data``, as their ETags by key and their full URLs."""
    if "*" in data:
        raise ValueError("a glob is expanded by DuckDB only")
    if data.endswith(".parquet"):
        base, key = split_source(data)
        meta = load_store(base, options).head(key)
        return {key: meta.etag}, [data]
    base = data if data.endswith("/") else f"{data}/"
    entries = [
        entry for entry in load_store(base, options).entries() if entry.path.endswith(".parquet")
    ]
    if not entries:
        raise ValueError("no parquet objects")
    versions = {entry.path: entry.etag for entry in sorted(entries, key=lambda e: e.path)}
    return versions, [f"{base}{key}" for key in versions]


def _describe(data: str, options: dict, urls: list[str]) -> dict[str, str]:
    """``DESCRIBE`` on the listed objects, read through the store's client."""
    con = connect(data, store_options=options, engine_options={"fastgeoapi_reader": "obstore"})
    try:
        files = ", ".join(f"'{url}'" for url in urls)
        scan = f"read_parquet([{files}], hive_partitioning=true, union_by_name=true)"
        # The URLs come from the store's own listing of ``data``, never from a request.
        # ruff: ignore[hardcoded-sql-expression]
        rows = con.execute(f"DESCRIBE SELECT * FROM {scan}").fetchall()  # nosec B608
    finally:
        con.close()
    return {row[0]: str(row[1]).upper() for row in rows}


def _entry_path(data: str, options: dict, cache_dir: Path | None) -> Path | None:
    if cache_dir is None:
        return None
    # The options take part in the key only through the digest: they may carry a secret.
    return cache_dir / f"{digest(data + json.dumps(options, sort_keys=True, default=str))}.json"


def _read_entry(entry: Path | None) -> dict | None:
    if entry is None:
        return None
    try:
        cached = json.loads(entry.read_text())
    except (OSError, ValueError):
        return None
    return cached if isinstance(cached, dict) and isinstance(cached.get("types"), dict) else None


def _write_entry(entry: Path, content: dict) -> None:
    try:
        entry.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        partial = entry.with_name(f"{entry.name}.{os.getpid()}.partial")
        partial.write_text(json.dumps(content))
        os.replace(partial, entry)
    except OSError as error:
        logger.warning(f"cannot keep the schema of {content['source']} ({error})")
