"""DuckDB session for the GeoParquet provider (ADR-0004).

Bucket data is read by **DuckDB itself** — `httpfs` for S3-compatible
and GCS, the `azure` extension for Azure — with the per-dataset settings
carried in a DuckDB secret. The earlier route, an obstore filesystem
registered through fsspec, made every query repay its bytes: DuckDB
caches the blocks it has fetched, but only on its own I/O path, and the
same query cost ~12 s on every repetition against 0,0 s natively. GDAL
behaves like DuckDB through `/vsicurl`, which is what identifies the
block cache as the variable rather than a DuckDB peculiarity.

obstore keeps the jobs where it is the better tool and costs nothing:
loading the configuration, writing the OpenAPI artifact, and enumerating
the objects of a dataset — DuckDB cannot glob through the bridge, and
enumerating once at construction is precise for both flat and
partitioned layouts.

Credentials stay in the standard environment variables of each cloud:
without explicit keys the secret uses DuckDB's own credential chain,
which reads the same variables obstore does. `skip_signature` asks for
anonymous access, which is what public datasets such as Overture need.

The `spatial` extension is expected to be vendored in the container
image; outside it we fall back to installing on demand.
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


# URL scheme → (DuckDB secret type, extension that provides it).
_NATIVE_READERS = {
    "s3": ("s3", "httpfs"),
    "s3a": ("s3", "httpfs"),
    "gs": ("gcs", "httpfs"),
    "gcs": ("gcs", "httpfs"),
    "az": ("azure", "azure"),
    "azure": ("azure", "azure"),
    "abfs": ("azure", "azure"),
    "abfss": ("azure", "azure"),
}

# Store options that map straight onto a DuckDB secret parameter.
_SECRET_PARAMS = (
    "region",
    "endpoint",
    "url_style",
    "use_ssl",
    "account_name",
    "connection_string",
    "key_id",
    "secret",
    "session_token",
)


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


# Options that steer this module rather than the engine: they must not
# reach `SET`, which only knows DuckDB's own configuration parameters.
_FASTGEOAPI_OPTION_PREFIX = "fastgeoapi_"


def _apply_engine_options(con, engine_options: dict) -> None:
    """Apply ``SET`` options, refusing names DuckDB does not know."""
    for name, value in engine_options.items():
        if str(name).startswith(_FASTGEOAPI_OPTION_PREFIX):
            continue
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
        reader = (engine_options or {}).get("fastgeoapi_reader", "native")
        if reader == "obstore":
            _register_obstore_filesystem(con, protocol, store_options)
        else:
            _configure_native_reader(con, protocol, store_options)
    return con


def _register_obstore_filesystem(con, protocol: str, store_options: dict | None) -> None:
    """The previous read path, kept as an escape hatch.

    Slower on repeated reads (no block cache) but useful when a store
    needs an obstore feature DuckDB's own reader does not have.
    """
    try:
        from obstore.fsspec import FsspecStore
    except ImportError as e:
        raise DuckDBUnavailableError(
            f"reading {protocol}:// through obstore needs its fsspec layer: "
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


def _configure_native_reader(con, protocol: str, store_options: dict | None) -> None:
    """Load DuckDB's own cloud reader and describe the store to it."""
    secret_type, extension = _NATIVE_READERS[protocol]
    try:
        con.load_extension(extension)
    except Exception:
        try:
            con.install_extension(extension)
            con.load_extension(extension)
        except Exception as e:
            raise DuckDBUnavailableError(
                f"the DuckDB '{extension}' extension is unavailable and cannot be "
                "installed here, which is what a read-only filesystem looks like: "
                "vendor it in the image, or point DUCKDB_EXTENSION_DIRECTORY at a "
                f"writable path. ({e})"
            ) from e

    options = dict(store_options or {})
    anonymous = bool(options.pop("skip_signature", False))
    parameters = [f"TYPE {secret_type}"]
    for name in _SECRET_PARAMS:
        if name in options and options[name] is not None:
            value = options.pop(name)
            literal = str(value).lower() if isinstance(value, bool) else f"'{value}'"
            parameters.append(f"{name.upper()} {literal}")
    if not anonymous and not any(p.startswith(("KEY_ID", "CONNECTION_STRING")) for p in parameters):
        # No explicit keys: let DuckDB read the same standard environment
        # variables obstore would. A deployment without credentials — a
        # public dataset — should say `skip_signature` instead.
        parameters.append("PROVIDER credential_chain")
    if options:
        logger.debug(f"store options not mapped to a DuckDB secret: {sorted(options)}")

    statement = f"CREATE OR REPLACE SECRET fastgeoapi_{secret_type} ({', '.join(parameters)})"
    try:
        con.execute(statement)
    except Exception as e:
        if "PROVIDER credential_chain" not in statement:
            raise DuckDBUnavailableError(f"could not configure the {protocol} store: {e}") from e
        # The credential chain validates eagerly and fails when there are
        # no credentials at all; fall back to the plain form so a
        # misconfiguration surfaces on the read, with a real message.
        logger.debug("no credentials found for the chain provider, using a plain secret")
        con.execute(statement.replace(", PROVIDER credential_chain", ""))
    logger.debug(f"native reader configured for {protocol}:// ({secret_type} secret)")


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
