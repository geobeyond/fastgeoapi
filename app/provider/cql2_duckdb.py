"""CQL2 (as a pygeofilter AST) to a DuckDB WHERE clause.

pygeoapi parses the ``filter`` parameter and hands providers a
pygeofilter AST, so this module only compiles. It derives from
pygeofilter's ``SQLEvaluator`` — whose spatial function names already
match DuckDB's — and fixes the three places where its output is not
valid DuckDB SQL:

1. geometry and envelope literals: upstream emits
   ``ST_GeomFromWKB(x'<hex>')``, but in DuckDB ``x'…'`` is a bit-string
   literal, so the call fails with "Unsupported geometry type in WKB".
   ``ST_GeomFromHEXWKB('<hex>')`` is the working form.
2. datetime literals: upstream's ``literal`` handler quotes strings and
   falls back to ``str(node)`` for everything else, which emits a bare
   datetime that DuckDB's parser rejects.
3. temporal operators: upstream's ``temporal`` handler is commented out,
   so every ``T_*`` node raises ``NotImplementedError`` from the
   evaluator base.
"""

from __future__ import annotations

from datetime import date, datetime, time

import shapely.geometry
from pygeofilter import ast, values
from pygeofilter.backends.evaluator import handle
from pygeofilter.backends.sql.evaluate import SQLEvaluator


class UnsupportedFilterError(Exception):
    """The filter names something this provider cannot serve."""


# CQL2 temporal operators over an instant → the SQL comparison DuckDB
# understands. Interval semantics (DURING, TCONTAINS, MEETS…) would need
# a second time column to be honest, so they are refused rather than
# approximated.
_TEMPORAL_OP_MAP = {
    ast.TemporalComparisonOp.AFTER: ">",
    ast.TemporalComparisonOp.BEFORE: "<",
    ast.TemporalComparisonOp.TEQUALS: "=",
}


class DuckDBSQLEvaluator(SQLEvaluator):
    """SQL evaluator speaking DuckDB's spatial dialect."""

    @handle(values.Geometry)
    def geometry(self, node: values.Geometry) -> str:
        """Geometry literal in the form DuckDB accepts."""
        return f"ST_GeomFromHEXWKB('{shapely.geometry.shape(node).wkb_hex}')"

    @handle(values.Envelope)
    def envelope(self, node: values.Envelope) -> str:
        """Envelope literal as a polygon, in DuckDB's form."""
        box = shapely.geometry.box(node.x1, node.y1, node.x2, node.y2)
        return f"ST_GeomFromHEXWKB('{box.wkb_hex}')"

    @handle(ast.TemporalPredicate, subclasses=True)
    def temporal(self, node, lhs, rhs) -> str:
        """Instant temporal comparison; intervals are refused."""
        try:
            operator = _TEMPORAL_OP_MAP[node.op]
        except KeyError as e:
            raise UnsupportedFilterError(
                f"temporal operator {node.op.name} is not supported by this provider"
            ) from e
        return f"({lhs} {operator} {rhs})"

    @handle(*values.LITERALS)
    def literal(self, node) -> str:
        """Literal value, quoted and escaped.

        Upstream interpolates strings raw (``f"'{node}'"``) and renders
        temporal values with ``str()``, so a value carrying a single
        quote escapes its SQL string — a cql2-json filter such as
        ``{"op": "=", "args": [{"property": "name"}, "x' OR 1=1 --"]}``
        becomes SQL logic. Doubling the quotes keeps a value a value.
        """
        if isinstance(node, (datetime, date, time)):
            return f"'{node.isoformat()}'"
        if isinstance(node, str):
            return "'" + node.replace("'", "''") + "'"
        return super().literal(node)

    @handle(ast.Like)
    def like(self, node, lhs) -> str:
        """LIKE with the pattern escaped the same way as any literal.

        The base implementation interpolates ``node.pattern`` directly,
        which is the same injection vector as :meth:`literal`.
        """
        pattern = node.pattern
        if node.wildcard != "%":
            pattern = pattern.replace(node.wildcard, "%")
        if node.singlechar != "_":
            pattern = pattern.replace(node.singlechar, "_")
        pattern = pattern.replace("'", "''")
        operator = "ILIKE" if node.nocase and self.use_ilike else "LIKE"
        negation = "NOT " if node.not_ else ""
        return f"{lhs} {negation}{operator} '{pattern}' ESCAPE '{node.escapechar}'"


def to_duckdb_where(root, field_mapping: dict[str, str]) -> str:
    """Compile a pygeofilter AST into a DuckDB WHERE clause.

    ``field_mapping`` maps a queryable property to its column name and
    doubles as the identifier allowlist: a property that is not in it is
    refused instead of reaching SQL.
    """
    try:
        return DuckDBSQLEvaluator(field_mapping, {}).evaluate(root)
    except KeyError as e:
        raise UnsupportedFilterError(f"unknown queryable property: {e}") from e
