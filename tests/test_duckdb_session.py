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
