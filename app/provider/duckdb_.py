"""DuckDB session for the GeoParquet provider (ADR-0004).

One engine for every source: DuckDB reads local paths directly, while
bucket URLs are routed through obstore's fsspec filesystem so the
storage layer stays the only place that knows about credentials and
endpoints. The ``spatial`` extension is expected to be vendored in the
container image; outside it we fall back to installing on demand.
"""

from __future__ import annotations

from app.config.logging import create_logger

logger = create_logger("app.provider.duckdb")

# Schemes served through obstore. The URL's OWN scheme is what gets
# registered: DuckDB dispatches a read to the filesystem registered
# under that protocol, so renaming `gs` to `gcs` on the way in would
# leave `gs://` reads unrouted and silently falling back to DuckDB's
# httpfs. `file` and `http(s)` are deliberately absent — DuckDB reads
# those natively and a local dataset needs no filesystem at all.
# `tests/test_duckdb_session.py` guards both invariants.
_CLOUD_SCHEMES = frozenset({"s3", "s3a", "gs", "gcs", "az", "azure", "abfs", "abfss", "adl"})


class DuckDBUnavailableError(RuntimeError):
    """DuckDB or its spatial extension could not be prepared."""


def protocol_for(source: str) -> str | None:
    """The protocol to register for a source, or None when it is local."""
    scheme, separator, _ = source.partition("://")
    if not separator:
        return None
    if scheme not in _CLOUD_SCHEMES:
        raise DuckDBUnavailableError(
            f"unsupported source scheme '{scheme}://': the GeoParquet provider reads "
            f"local paths and {', '.join(sorted(_CLOUD_SCHEMES))}"
        )
    return scheme


def connect(source: str, store_options: dict | None = None):
    """Open a connection ready to scan ``source``.

    ``store_options`` is handed to obstore as the store configuration:
    ``region``, ``skip_signature`` for public datasets, ``endpoint`` for
    an S3-compatible service. Without it obstore signs every request and
    goes looking for credentials — on a public bucket that means ~20s of
    EC2-metadata retries and then a failure.
    """
    try:
        import duckdb
    except ImportError as e:  # pragma: no cover - exercised by the extra
        raise DuckDBUnavailableError(
            "the GeoParquet provider needs the 'geoparquet' extra: "
            "pip install 'fastgeoapi[geoparquet]'"
        ) from e

    con = duckdb.connect()
    try:
        con.load_extension("spatial")
    except duckdb.Error:
        logger.debug("spatial extension not vendored, installing on demand")
        con.install_extension("spatial")
        con.load_extension("spatial")

    protocol = protocol_for(source)
    if protocol is not None:
        try:
            from obstore.fsspec import FsspecStore
        except ImportError as e:
            raise DuckDBUnavailableError(
                f"reading {protocol}:// needs obstore's fsspec layer: "
                "pip install 'fastgeoapi[geoparquet]'"
            ) from e
        # ty: the constructor is overloaded per literal protocol, and the
        # scheme is only known at runtime; _CLOUD_SCHEMES keeps it within
        # the set obstore serves.
        store = FsspecStore(  # ty: ignore[no-matching-overload]
            protocol=protocol,
            config=store_options or None,
        )
        con.register_filesystem(store)
        logger.debug(f"registered the obstore filesystem for {protocol}://")
    return con


def scan_expression(source: str) -> str:
    """Build the ``read_parquet`` fragment for a file, glob or directory.

    A source that already names a file or carries a glob is used as is;
    anything else is treated as a dataset root, which is the shape of a
    hive-partitioned export.
    """
    target = source
    if not (source.endswith(".parquet") or "*" in source):
        target = f"{source.rstrip('/')}/**/*.parquet"
    return f"read_parquet('{target}', hive_partitioning=true, union_by_name=true)"
