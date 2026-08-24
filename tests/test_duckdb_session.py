"""DuckDB session helper: one engine, local paths and bucket URLs.

Local sources are read directly by DuckDB; cloud sources go through the
obstore filesystem (ADR-0003's layer stays the only place that knows
about credentials and endpoints).

Every app import stays at module level ON PURPOSE. Other test modules
purge ``app.*`` from ``sys.modules`` in their fixtures, so an import
inside a test would bind a SECOND ``DuckDBUnavailableError`` class and
``pytest.raises`` would not catch the one ``connect`` actually raises.
"""

import pytest

from app.provider.duckdb_ import (
    _CLOUD_SCHEMES,
    DuckDBUnavailableError,
    connect,
    protocol_for,
    scan_expression,
)


def _write_dataset(root) -> str:
    """Create a hive-partitioned GeoParquet dataset with DuckDB itself."""
    con = connect(str(root))
    con.execute(
        f"""
        COPY (
            SELECT 1 AS id, 'alpha' AS name, 'it' AS country, ST_Point(12.5, 41.9) AS geom
            UNION ALL SELECT 2, 'beta', 'it', ST_Point(9.2, 45.5)
            UNION ALL SELECT 3, 'gamma', 'fr', ST_Point(2.3, 48.9)
        ) TO '{root}/ds' (FORMAT parquet, PARTITION_BY (country), OVERWRITE_OR_IGNORE)
        """
    )
    return f"{root}/ds"


def test_connection_has_spatial(tmp_path):
    con = connect(str(tmp_path))
    assert con.execute("SELECT ST_AsText(ST_Point(1, 2))").fetchone()[0] == "POINT (1 2)"


def test_scan_expression_adds_the_glob_for_a_directory(tmp_path):
    dataset = _write_dataset(tmp_path)
    expr = scan_expression(dataset)
    assert "read_parquet" in expr
    assert "hive_partitioning" in expr
    assert dataset in expr


def test_scan_expression_keeps_an_explicit_file():
    expr = scan_expression("s3://bucket/one.parquet")
    assert "s3://bucket/one.parquet" in expr
    assert "**" not in expr


def test_local_dataset_is_readable_with_partition_pruning(tmp_path):
    dataset = _write_dataset(tmp_path)
    con = connect(dataset)
    total = con.execute(f"SELECT count(*) FROM {scan_expression(dataset)}").fetchone()[0]
    assert total == 3
    pruned = con.execute(
        f"SELECT count(*) FROM {scan_expression(dataset)} WHERE country = 'it'"
    ).fetchone()[0]
    assert pruned == 2


@pytest.mark.parametrize(
    ("source", "scheme"),
    [
        ("s3://bucket/ds", "s3"),
        ("gs://bucket/ds", "gs"),
        ("gcs://bucket/ds", "gcs"),
        ("az://container/ds", "az"),
        ("azure://container/ds", "azure"),
        ("abfs://container/ds", "abfs"),
    ],
)
def test_cloud_sources_register_the_url_scheme(source, scheme):
    """The filesystem must be registered under the URL's OWN scheme.

    DuckDB routes a read by the protocol the filesystem is registered
    with, so mapping ``gs://`` onto ``gcs`` would leave the read
    unrouted — DuckDB would fall back to its own httpfs and never reach
    obstore. obstore supports every one of these scheme names.
    """
    con = connect(source)  # registration itself needs no network
    assert con.execute("SELECT 1").fetchone()[0] == 1


def test_every_accepted_scheme_is_one_obstore_serves():
    """Drift guard: our scheme set must stay a subset of obstore's own.

    An obstore upgrade that drops or renames a protocol makes this red
    instead of turning cloud reads into silent httpfs fallbacks.
    """
    from obstore.fsspec import SUPPORTED_PROTOCOLS

    assert _CLOUD_SCHEMES <= set(SUPPORTED_PROTOCOLS), (
        f"no longer served by obstore: {sorted(_CLOUD_SCHEMES - set(SUPPORTED_PROTOCOLS))}"
    )


@pytest.mark.parametrize(
    ("source", "scheme"),
    [
        ("s3://bucket/ds", "s3"),
        ("gs://bucket/ds", "gs"),
        ("gcs://bucket/ds", "gcs"),
        ("az://container/ds", "az"),
        ("abfs://container/ds", "abfs"),
    ],
)
def test_the_filesystem_handed_to_duckdb_carries_the_url_scheme(source, scheme):
    """Regression guard for the routing invariant.

    DuckDB dispatches a read to the filesystem registered under the URL's
    protocol, so the object we hand it must answer with the scheme the
    source actually uses. Reintroducing a rename in ``protocol_for``
    (``gs`` → ``gcs``) makes this red; asserting ``protocol_for`` alone
    would only restate our own table.
    """
    from obstore.fsspec import FsspecStore

    # Same overload caveat as the module: the scheme is runtime data.
    store = FsspecStore(protocol=protocol_for(source))  # ty: ignore[no-matching-overload]
    protocols = store.protocol if isinstance(store.protocol, tuple) else (store.protocol,)
    assert scheme in protocols


def test_local_sources_have_no_protocol(tmp_path):
    assert protocol_for(str(tmp_path)) is None
    assert protocol_for("pygeoapi-config.yml") is None


def test_unsupported_scheme_is_refused():
    with pytest.raises(DuckDBUnavailableError, match="ftp"):
        connect("ftp://host/ds")


def test_store_options_reach_the_filesystem():
    """Cloud sources need per-dataset store options.

    Public datasets (Overture) must be read anonymously and name their
    region; an S3-compatible endpoint (Tigris, MinIO) needs its URL.
    Without a way to pass these, obstore tries to sign the request,
    goes looking for credentials on the EC2 metadata endpoint and fails
    after ~20s of retries — a public bucket is simply unreadable.
    """
    con = connect(
        "s3://overturemaps-us-west-2/release/x/part-0.parquet",
        store_options={"region": "us-west-2", "skip_signature": True},
    )
    assert con.execute("SELECT 1").fetchone()[0] == 1


def test_store_options_are_optional():
    con = connect("s3://bucket/ds")
    assert con.execute("SELECT 1").fetchone()[0] == 1


# --- Runtimes with a read-only filesystem (AWS Lambda and friends) ---------
#
# fastgeoapi ships a Lambda path (`AWS_LAMBDA_DEPLOY` + Mangum). There the
# filesystem is read-only except /tmp, and DuckDB's defaults do not fit:
# `temp_directory` is `.tmp` relative to the working directory, and a
# missing extension triggers an install into ~/.duckdb.


def test_temp_directory_is_writable():
    """DuckDB must spill somewhere it is allowed to write.

    The default is `.tmp` next to the working directory, which on a
    read-only runtime fails the moment a query needs to spill.
    """
    import tempfile

    con = connect("/tmp")
    configured = con.execute("SELECT current_setting('temp_directory')").fetchone()[0]
    assert configured
    assert configured.startswith(tempfile.gettempdir()) or configured.startswith("/tmp")


def test_temp_directory_honours_tmpdir(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    con = connect("/tmp")
    assert str(tmp_path) in con.execute("SELECT current_setting('temp_directory')").fetchone()[0]


def test_a_missing_extension_that_cannot_be_installed_says_so(monkeypatch):
    """The failure must name the cause and the remedy, not leak a raw error.

    Today the fallback calls install_extension unconditionally: on a
    read-only filesystem that raises something opaque about ~/.duckdb at
    the first cold start.
    """
    import duckdb as duckdb_module

    def refuse_load(self, *args, **kwargs):
        raise duckdb_module.IOException("Extension not found")

    def refuse_install(self, *args, **kwargs):
        raise duckdb_module.IOException("Cannot write to extension directory")

    monkeypatch.setattr(duckdb_module.DuckDBPyConnection, "load_extension", refuse_load)
    monkeypatch.setattr(duckdb_module.DuckDBPyConnection, "install_extension", refuse_install)

    with pytest.raises(DuckDBUnavailableError, match="read-only"):
        connect("/tmp")


def test_engine_options_from_the_provider_definition():
    """Deployment-specific limits travel with the configuration."""
    con = connect("/tmp", engine_options={"memory_limit": "256MB", "threads": 2})
    # DuckDB normalises the unit, so 256MB reads back as "244.1 MiB":
    # assert the magnitude rather than the spelling.
    limit = con.execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert limit.endswith("MiB"), limit
    assert float(limit.split()[0]) < 1024, limit
    assert con.execute("SELECT current_setting('threads')").fetchone()[0] == 2


def test_an_unknown_engine_option_is_refused():
    """A typo must fail loudly at startup, not silently do nothing."""
    with pytest.raises(DuckDBUnavailableError, match="memory_limitt"):
        connect("/tmp", engine_options={"memory_limitt": "256MB"})


def test_engine_option_names_are_validated():
    """The option name reaches SQL as an identifier, so it is constrained."""
    with pytest.raises(DuckDBUnavailableError, match="invalid"):
        connect("/tmp", engine_options={"memory_limit; DROP TABLE x": "1"})
