"""DuckDB session for the GeoParquet provider (ADR-0004).

One engine for every source: DuckDB reads local paths directly, while
bucket URLs are routed through obstore's fsspec filesystem so the
storage layer stays the only place that knows about credentials and
endpoints. The ``spatial`` extension is expected to be vendored in the
container image; outside it we fall back to installing on demand.
"""

from __future__ import annotations

import os
import re
import tempfile

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


# Engine option names reach SQL as identifiers (`SET <name>=…`), so they
# are constrained rather than trusted: a configuration file is not a
# place to smuggle SQL from.
_OPTION_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


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


def _writable_temp_directory() -> str:
    """A directory DuckDB may spill into.

    Its default is ``.tmp`` relative to the working directory, which is
    read-only on Lambda-style runtimes; ``TMPDIR`` is what those runtimes
    set (``/tmp``), and ``tempfile`` honours it everywhere else.
    """
    return os.environ.get("TMPDIR") or tempfile.gettempdir()


def _apply_engine_options(con, engine_options: dict) -> None:
    """Apply ``SET`` options, refusing names DuckDB does not know."""
    for name, value in engine_options.items():
        if not _OPTION_NAME.match(str(name)):
            raise DuckDBUnavailableError(f"invalid DuckDB option name: {name!r}")
        literal = value if isinstance(value, (int, float)) else f"'{value}'"
        try:
            con.execute(f"SET {name}={literal}")
        except Exception as e:
            raise DuckDBUnavailableError(f"DuckDB rejected the option {name!r}: {e}") from e


def connect(
    source: str,
    store_options: dict | None = None,
    engine_options: dict | None = None,
):
    """Open a connection ready to scan ``source``.

    ``store_options`` is handed to obstore as the store configuration:
    ``region``, ``skip_signature`` for public datasets, ``endpoint`` for
    an S3-compatible service. Without it obstore signs every request and
    goes looking for credentials — on a public bucket that means ~20s of
    EC2-metadata retries and then a failure.

    ``engine_options`` are DuckDB settings for the deployment rather than
    the dataset — ``memory_limit`` and ``threads`` matter on a function
    runtime, where the engine would otherwise size itself against the
    host's resources instead of the function's.
    """
    try:
        import duckdb
    except ImportError as e:  # pragma: no cover - exercised by the extra
        raise DuckDBUnavailableError(
            "the GeoParquet provider needs the 'geoparquet' extra: "
            "pip install 'fastgeoapi[geoparquet]'"
        ) from e

    con = duckdb.connect()
    con.execute(f"SET temp_directory='{_writable_temp_directory()}'")
    extension_directory = os.environ.get("DUCKDB_EXTENSION_DIRECTORY")
    if extension_directory:
        con.execute(f"SET extension_directory='{extension_directory}'")
    if engine_options:
        _apply_engine_options(con, engine_options)

    try:
        con.load_extension("spatial")
    except duckdb.Error as load_error:
        # Installing writes into the extension directory, which on a
        # read-only runtime (Lambda and friends) is not writable at all:
        # say what happened and what to do about it, instead of leaking
        # an error about a path the operator never chose.
        logger.debug("spatial extension not vendored, installing on demand")
        try:
            con.install_extension("spatial")
            con.load_extension("spatial")
        except Exception as install_error:
            raise DuckDBUnavailableError(
                "the DuckDB spatial extension is unavailable and cannot be "
                "installed here, which is what a read-only filesystem looks "
                "like: vendor the extension in the image, or point "
                "DUCKDB_EXTENSION_DIRECTORY at a writable path. "
                f"(load: {load_error}; install: {install_error})"
            ) from install_error

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


def scan_expression(source: str, store_options: dict | None = None) -> str:
    """Build the ``read_parquet`` fragment for a file, glob or directory.

    A source naming a single file, or carrying its own glob, is used as
    is. A directory is expanded — and how depends on where it lives:

    - locally DuckDB globs the filesystem itself;
    - on a bucket it cannot. Reading Overture through the obstore
      filesystem showed that no wildcard survives that bridge — an
      explicit file works while ``*.parquet`` and ``**/*.parquet`` both
      raise "No files found" — which would leave every multi-file cloud
      dataset unusable. So the objects are listed through the storage
      layer and handed to DuckDB as explicit paths.
    """
    if source.endswith(".parquet") or "*" in source:
        target = f"'{source}'"
    elif protocol_for(source) is None:
        target = f"'{source.rstrip('/')}/**/*.parquet'"
    else:
        target = _enumerate_cloud_parquet(source, store_options)
    return f"read_parquet({target}, hive_partitioning=true, union_by_name=true)"


def _enumerate_cloud_parquet(source: str, store_options: dict | None) -> str:
    """List the parquet objects under a bucket prefix, as a SQL list."""
    from app.provider.storage import load_store

    base = source if source.endswith("/") else f"{source}/"
    store = load_store(base, store_options=store_options)
    keys = [key for key in store.keys() if key.endswith(".parquet")]
    if not keys:
        raise DuckDBUnavailableError(f"no parquet objects under {source}")
    logger.debug(f"{len(keys)} parquet object(s) enumerated under {source}")
    return "[" + ", ".join(f"'{base}{key}'" for key in keys) + "]"
