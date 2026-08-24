"""CQL2 to DuckDB SQL: every case is EXECUTED, not just string-compared.

pygeofilter's sql backend gets us most of the way, but three of its
outputs are invalid for DuckDB (hex WKB as a bit-string literal,
unquoted datetimes, missing temporal operators). Comparing strings
would have hidden all three.
"""

import pytest
from pygeofilter.parsers.cql2_json import parse as parse_json
from pygeofilter.parsers.cql2_text import parse as parse_text

from app.provider.cql2_duckdb import UnsupportedFilterError, to_duckdb_where
from app.provider.duckdb_ import connect

FIELDS = {"id": "id", "name": "name", "country": "country", "geom": "geom", "ts": "ts"}


@pytest.fixture(scope="module")
def con():
    connection = connect("/tmp")
    connection.execute(
        """
        CREATE TABLE t AS
        SELECT 1 AS id, 'alpha' AS name, 'it' AS country,
               ST_Point(12.5, 41.9) AS geom,
               TIMESTAMP '2021-06-01 10:00:00' AS ts
        UNION ALL
        SELECT 2, 'beta', 'fr', ST_Point(2.3, 48.9), TIMESTAMP '2023-01-15 08:00:00'
        """
    )
    return connection


def _matches(con, cql: str) -> list[int]:
    where = to_duckdb_where(parse_text(cql), FIELDS)
    return [row[0] for row in con.execute(f"SELECT id FROM t WHERE {where} ORDER BY id").fetchall()]


@pytest.mark.parametrize(
    ("cql", "expected"),
    [
        ("name = 'alpha'", [1]),
        ("id > 1", [2]),
        ("id >= 1 AND country = 'it'", [1]),
        ("name = 'alpha' OR name = 'beta'", [1, 2]),
        ("NOT name = 'alpha'", [2]),
        ("name LIKE 'al%'", [1]),
        ("name IN ('alpha', 'gamma')", [1]),
        ("id BETWEEN 2 AND 5", [2]),
    ],
)
def test_scalar_operators(con, cql, expected):
    assert _matches(con, cql) == expected


def test_spatial_intersects_runs_in_the_engine(con):
    """The hex-WKB literal must be ST_GeomFromHEXWKB.

    With the upstream ``x'...'`` form DuckDB reads a bit-string and
    raises "Unsupported geometry type in WKB".
    """
    cql = "S_INTERSECTS(geom, POLYGON((11 41, 14 41, 14 43, 11 43, 11 41)))"
    assert _matches(con, cql) == [1]


def test_spatial_within(con):
    cql = "S_WITHIN(geom, POLYGON((0 40, 20 40, 20 50, 0 50, 0 40)))"
    assert _matches(con, cql) == [1, 2]


def test_datetime_literal_is_quoted(con):
    """Upstream emits a bare datetime, which DuckDB cannot parse."""
    assert _matches(con, "ts > TIMESTAMP('2022-01-01T00:00:00Z')") == [2]


def test_temporal_operator_is_implemented(con):
    """``temporal`` is commented out upstream: T_AFTER must still work.

    Note the INFIX form: pygeofilter's cql2-text grammar treats T_AFTER
    as an operator token, so ``T_AFTER(a, b)`` does not even parse.
    """
    assert _matches(con, "ts T_AFTER TIMESTAMP('2022-01-01T00:00:00Z')") == [2]
    assert _matches(con, "ts T_BEFORE TIMESTAMP('2022-01-01T00:00:00Z')") == [1]


def test_unsupported_temporal_operator_is_refused():
    """Interval semantics would need a second time column to be honest."""
    with pytest.raises(UnsupportedFilterError, match="TOVERLAPS"):
        to_duckdb_where(parse_text("ts T_INTERSECTS TIMESTAMP('2022-01-01T00:00:00Z')"), FIELDS)


def test_cql2_json_path(con):
    where = to_duckdb_where(parse_json({"op": "=", "args": [{"property": "name"}, "beta"]}), FIELDS)
    assert [r[0] for r in con.execute(f"SELECT id FROM t WHERE {where}").fetchall()] == [2]


def test_unknown_property_is_refused():
    """The field mapping doubles as the identifier allowlist."""
    with pytest.raises(UnsupportedFilterError, match="secret_column"):
        to_duckdb_where(parse_text("secret_column = 1"), FIELDS)


def test_injection_in_a_value_stays_a_value(con):
    """A quote-laden literal must not break out of its SQL string.

    cql2-json accepts arbitrary strings, and upstream's ``literal``
    interpolates them unescaped: the value below turns into
    ``("name" = 'x' OR 1=1 --')``, where ``OR 1=1`` becomes SQL logic
    and would return every row. The dialect must double the quotes.
    """
    where = to_duckdb_where(
        parse_json({"op": "=", "args": [{"property": "name"}, "x' OR 1=1 --"]}),
        FIELDS,
    )
    rows = con.execute(f"SELECT id FROM t WHERE {where} ORDER BY id").fetchall()
    assert rows == []  # no row has that literal name, and no row is unlocked


def test_injection_via_like_pattern_stays_a_pattern(con):
    """The same escaping must hold for LIKE patterns."""
    where = to_duckdb_where(
        parse_json({"op": "like", "args": [{"property": "name"}, "%' OR 1=1 --"]}),
        FIELDS,
    )
    rows = con.execute(f"SELECT id FROM t WHERE {where} ORDER BY id").fetchall()
    assert rows == []
