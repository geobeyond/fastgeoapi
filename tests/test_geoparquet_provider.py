"""GeoParquet provider on DuckDB, against DuckDB-generated fixtures.

Fixtures are written by DuckDB itself (it emits GeoParquet ``geo``
metadata), so the tests exercise the same reader path a cloud dataset
would take — LocalStore and bucket differ only in credentials.
"""

import pytest

from app.provider.duckdb_ import connect
from app.provider.geoparquet import GeoParquetProvider


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> str:
    root = tmp_path_factory.mktemp("geoparquet")
    con = connect(str(root))
    con.execute(
        f"""
        COPY (
            SELECT 1 AS id, 'alpha' AS name, 'it' AS country, 10 AS pop,
                   TIMESTAMP '2021-06-01 10:00:00' AS ts, ST_Point(12.5, 41.9) AS geom
            UNION ALL SELECT 2, 'beta', 'it', 20, TIMESTAMP '2022-06-01 10:00:00',
                   ST_Point(9.2, 45.5)
            UNION ALL SELECT 3, 'gamma', 'fr', 30, TIMESTAMP '2023-06-01 10:00:00',
                   ST_Point(2.3, 48.9)
        ) TO '{root}/ds' (FORMAT parquet, PARTITION_BY (country), OVERWRITE_OR_IGNORE)
        """
    )
    return f"{root}/ds"


@pytest.fixture
def provider(dataset) -> GeoParquetProvider:
    return GeoParquetProvider(
        {
            "name": "app.provider.geoparquet.GeoParquetProvider",
            "type": "feature",
            "data": dataset,
            "id_field": "id",
            "geometry_column": "geom",
            "time_field": "ts",
        }
    )


def test_fields_expose_the_queryable_columns(provider):
    fields = provider.get_fields()
    assert set(fields) == {"id", "name", "country", "pop", "ts"}  # geometry excluded
    assert fields["name"]["type"] == "string"
    assert fields["pop"]["type"] == "integer"
    assert fields["ts"]["type"] == "string"
    assert fields["ts"]["format"] == "date-time"


def test_geometry_column_is_not_a_queryable_field(provider):
    assert "geom" not in provider.get_fields()


def test_missing_id_field_is_rejected(dataset):
    from pygeoapi.provider.base import ProviderQueryError

    with pytest.raises(ProviderQueryError):
        GeoParquetProvider(
            {
                "name": "app.provider.geoparquet.GeoParquetProvider",
                "type": "feature",
                "data": dataset,
            }
        )


def test_unknown_geometry_column_is_rejected(dataset):
    from pygeoapi.provider.base import ProviderQueryError

    with pytest.raises(ProviderQueryError, match="nope"):
        GeoParquetProvider(
            {
                "name": "app.provider.geoparquet.GeoParquetProvider",
                "type": "feature",
                "data": dataset,
                "id_field": "id",
                "geometry_column": "nope",
            }
        )


def test_query_returns_a_feature_collection(provider):
    fc = provider.query()
    assert fc["type"] == "FeatureCollection"
    assert fc["numberReturned"] == 3
    assert sorted(f["id"] for f in fc["features"]) == [1, 2, 3]
    first = fc["features"][0]
    assert first["type"] == "Feature"
    assert first["geometry"]["type"] == "Point"
    assert "name" in first["properties"]
    assert "geom" not in first["properties"]  # geometry is not a property


def test_limit_and_offset(provider):
    page = provider.query(limit=2, sortby=[{"property": "id", "order": "+"}])
    assert [f["id"] for f in page["features"]] == [1, 2]
    nxt = provider.query(offset=2, limit=2, sortby=[{"property": "id", "order": "+"}])
    assert [f["id"] for f in nxt["features"]] == [3]


def test_sortby_descending(provider):
    fc = provider.query(sortby=[{"property": "id", "order": "-"}])
    assert [f["id"] for f in fc["features"]] == [3, 2, 1]


def test_select_properties_projects(provider):
    fc = provider.query(select_properties=["name"])
    assert set(fc["features"][0]["properties"]) == {"name"}


def test_skip_geometry(provider):
    fc = provider.query(skip_geometry=True)
    assert fc["features"][0]["geometry"] is None


def test_properties_filter_is_an_exact_match(provider):
    fc = provider.query(properties=[("country", "fr")])
    assert [f["id"] for f in fc["features"]] == [3]


def test_hits_only_counts(provider):
    fc = provider.query(resulttype="hits")
    assert fc["numberMatched"] == 3
    assert fc["features"] == []


def test_unknown_select_property_is_refused(provider):
    from pygeoapi.provider.base import ProviderQueryError

    with pytest.raises(ProviderQueryError, match="nope"):
        provider.query(select_properties=["nope"])


def test_bbox_filter(provider):
    fc = provider.query(bbox=[11, 41, 14, 43])
    assert [f["id"] for f in fc["features"]] == [1]


def test_bbox_with_hits(provider):
    assert provider.query(bbox=[11, 41, 14, 43], resulttype="hits")["numberMatched"] == 1


def test_datetime_instant_and_interval(provider):
    assert [f["id"] for f in provider.query(datetime_="2022-06-01T10:00:00Z")["features"]] == [2]
    fc = provider.query(datetime_="2022-01-01T00:00:00Z/2024-01-01T00:00:00Z")
    assert sorted(f["id"] for f in fc["features"]) == [2, 3]


def test_open_ended_interval(provider):
    fc = provider.query(datetime_="2022-01-01T00:00:00Z/..")
    assert sorted(f["id"] for f in fc["features"]) == [2, 3]


def test_datetime_without_time_field_is_refused(dataset):
    from pygeoapi.provider.base import ProviderQueryError

    without_time = GeoParquetProvider(
        {
            "name": "app.provider.geoparquet.GeoParquetProvider",
            "type": "feature",
            "data": dataset,
            "id_field": "id",
            "geometry_column": "geom",
        }
    )
    with pytest.raises(ProviderQueryError, match="time_field"):
        without_time.query(datetime_="2022-06-01T10:00:00Z")


def test_cql2_scalar_filter(provider):
    from pygeofilter.parsers.cql2_text import parse

    fc = provider.query(filterq=parse("pop > 15 AND country = 'it'"))
    assert [f["id"] for f in fc["features"]] == [2]


def test_cql2_spatial_filter(provider):
    from pygeofilter.parsers.cql2_text import parse

    fc = provider.query(
        filterq=parse("S_INTERSECTS(geom, POLYGON((11 41, 14 41, 14 43, 11 43, 11 41)))")
    )
    assert [f["id"] for f in fc["features"]] == [1]


def test_cql2_on_an_unknown_property_is_a_provider_error(provider):
    from pygeoapi.provider.base import ProviderQueryError
    from pygeofilter.parsers.cql2_text import parse

    with pytest.raises(ProviderQueryError):
        provider.query(filterq=parse("nope = 1"))


def test_filters_combine(provider):
    from pygeofilter.parsers.cql2_text import parse

    fc = provider.query(bbox=[8, 44, 11, 47], filterq=parse("pop > 15"))
    assert [f["id"] for f in fc["features"]] == [2]


def test_get_returns_a_single_feature(provider):
    feature = provider.get(2)
    assert feature["id"] == 2
    assert feature["properties"]["name"] == "beta"
    assert feature["geometry"]["type"] == "Point"


def test_get_accepts_a_string_identifier(provider):
    assert provider.get("2")["id"] == 2


def test_get_missing_identifier_raises_item_not_found(provider):
    from pygeoapi.provider.base import ProviderItemNotFoundError

    with pytest.raises(ProviderItemNotFoundError):
        provider.get(999)


def test_get_does_not_interpolate_the_identifier(provider):
    """The identifier is bound as a parameter, never spliced into SQL."""
    from pygeoapi.provider.base import ProviderItemNotFoundError

    with pytest.raises(ProviderItemNotFoundError):
        provider.get("1' OR '1'='1")


def test_concurrent_queries_are_correct(tmp_path_factory):
    """pygeoapi calls providers from a threadpool, so query() must be
    safe under concurrency.

    A single DuckDB connection shared across threads loses results: one
    thread's execute() resets another's pending result and fetchone()
    returns None, so a fraction of the requests silently answer wrong.
    DuckDB's documented pattern is a cursor per operation.
    """
    from concurrent.futures import ThreadPoolExecutor

    root = tmp_path_factory.mktemp("concurrency")
    con = connect(str(root))
    con.execute(
        f"""
        COPY (
            SELECT i AS id, 'name-' || i AS name, ST_Point(i % 180, i % 90) AS geom
            FROM range(200000) tbl(i)
        ) TO '{root}/big.parquet' (FORMAT parquet)
        """
    )
    provider = GeoParquetProvider(
        {
            "name": "app.provider.geoparquet.GeoParquetProvider",
            "type": "feature",
            "data": f"{root}/big.parquet",
            "id_field": "id",
            "geometry_column": "geom",
        }
    )

    def hit(_):
        return provider.query(resulttype="hits")["numberMatched"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(hit, range(32)))

    assert counts == [200000] * 32, f"anomalies: {sorted(set(counts))}"


# --- Covering bbox pruning and the count option -----------------------------
#
# Measured on a 578 MB Overture file over S3: ST_Intersects on the geometry
# column took 64s because a spatial predicate cannot use parquet statistics,
# while the same filter expressed on the GeoParquet covering column took 19s
# — DuckDB prunes row groups. The covering test is only ever a superset, so
# the exact predicate stays.


@pytest.fixture(scope="module")
def covered_dataset(tmp_path_factory) -> str:
    """A dataset carrying a GeoParquet-style ``bbox`` covering column.

    The diagonal line is the interesting row: its bbox spans the whole
    square while the line itself misses a corner window, so a query that
    trusted the covering column alone would return it.
    """
    root = tmp_path_factory.mktemp("covered")
    con = connect(str(root))
    con.execute(
        f"""
        COPY (
            SELECT 1 AS id, 'point-in' AS name,
                   ST_Point(12.5, 41.9) AS geom,
                   {{'xmin': 12.5, 'xmax': 12.5, 'ymin': 41.9, 'ymax': 41.9}} AS bbox
            UNION ALL
            SELECT 2, 'point-out', ST_Point(2.3, 48.9),
                   {{'xmin': 2.3, 'xmax': 2.3, 'ymin': 48.9, 'ymax': 48.9}}
            UNION ALL
            SELECT 3, 'diagonal', ST_GeomFromText('LINESTRING(0 0, 10 10)'),
                   {{'xmin': 0.0, 'xmax': 10.0, 'ymin': 0.0, 'ymax': 10.0}}
        ) TO '{root}/ds.parquet' (FORMAT parquet)
        """
    )
    return f"{root}/ds.parquet"


@pytest.fixture
def covered_provider(covered_dataset) -> GeoParquetProvider:
    return GeoParquetProvider(
        {
            "name": "app.provider.geoparquet.GeoParquetProvider",
            "type": "feature",
            "data": covered_dataset,
            "id_field": "id",
            "geometry_column": "geom",
        }
    )


def test_covering_column_is_detected(covered_provider):
    assert covered_provider.covering_bbox_column == "bbox"


def test_covering_column_is_not_a_queryable_field(covered_provider):
    """It is metadata, not a property a client filters on."""
    assert "bbox" not in covered_provider.get_fields()


def test_bbox_clause_prunes_with_the_covering_column(covered_provider):
    clause = covered_provider._bbox_clause([11, 41, 14, 43])
    assert '"bbox".xmin' in clause  # cheap pre-filter, uses row-group stats
    assert "ST_Intersects" in clause  # exactness kept


def test_bbox_clause_without_a_covering_column(provider):
    clause = provider._bbox_clause([11, 41, 14, 43])
    assert '"bbox"' not in clause
    assert "ST_Intersects" in clause


def test_pruning_does_not_change_the_answer(covered_provider):
    """The corner window touches the diagonal's bbox but not the line."""
    corner = covered_provider.query(bbox=[9.0, 0.0, 10.0, 0.5])
    assert [f["id"] for f in corner["features"]] == []

    hit = covered_provider.query(bbox=[11, 41, 14, 43])
    assert [f["id"] for f in hit["features"]] == [1]

    crossing = covered_provider.query(bbox=[4.0, 4.0, 6.0, 6.0])
    assert [f["id"] for f in crossing["features"]] == [3]


def test_count_can_be_disabled(covered_dataset):
    """``count: false`` skips the count: on a remote dataset it cost 15s."""
    provider = GeoParquetProvider(
        {
            "name": "app.provider.geoparquet.GeoParquetProvider",
            "type": "feature",
            "data": covered_dataset,
            "id_field": "id",
            "geometry_column": "geom",
            "count": False,
        }
    )
    fc = provider.query(limit=1)
    assert "numberMatched" not in fc
    assert fc["numberReturned"] == 1
    # A hits request asks for exactly that number, so it still counts.
    assert provider.query(resulttype="hits")["numberMatched"] == 3


def test_count_is_on_by_default(covered_provider):
    assert covered_provider.query(limit=1)["numberMatched"] == 3


def test_engine_options_reach_the_session(dataset):
    """Deployment limits travel with the provider definition.

    On a function runtime the engine must be sized against the function,
    not the host it happens to land on.
    """
    provider = GeoParquetProvider(
        {
            "name": "app.provider.geoparquet.GeoParquetProvider",
            "type": "feature",
            "data": dataset,
            "id_field": "id",
            "geometry_column": "geom",
            "engine_options": {"memory_limit": "256MB"},
        }
    )
    limit = provider._cursor().execute("SELECT current_setting('memory_limit')").fetchone()[0]
    assert limit.endswith("MiB"), limit


# --- A committed fixture written the way other tools write GeoParquet ------
#
# Every fixture above is produced by DuckDB, so its geometry column has
# DuckDB's native GEOMETRY type. A file from GeoPandas, GDAL or Sedona
# carries the geometry as a WKB BLOB instead, and the provider has a
# branch for exactly that — until now exercised by nothing.

FIXTURE = "tests/data/lakes.parquet"


def test_the_committed_fixture_is_shaped_like_a_third_party_file():
    """The fixture must keep the shape it is there to represent.

    If someone regenerates it with a plain `COPY ... TO` the geometry
    silently becomes DuckDB's own type, the WKB branch stops being
    covered, and nothing else would notice.
    """
    from app.provider.duckdb_ import connect

    described = (
        connect(FIXTURE).execute(f"DESCRIBE SELECT * FROM read_parquet('{FIXTURE}')").fetchall()
    )
    types = {row[0]: str(row[1]) for row in described}
    assert types["geometry"] == "BLOB", types
    assert types["bbox"].startswith("STRUCT"), types


def test_a_third_party_geoparquet_is_served(tmp_path):
    """The provider reads WKB geometries, not only the ones DuckDB wrote."""
    provider = GeoParquetProvider(
        {
            "name": "GeoParquet",
            "type": "feature",
            "data": FIXTURE,
            "id_field": "id",
            "geometry_column": "geometry",
        }
    )
    result = provider.query(bbox=[11.0, 41.0, 13.0, 43.0], limit=10)
    assert result["features"], result
    assert result["features"][0]["geometry"]["type"] == "Point"
