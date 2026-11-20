"""CQL2 (as a pygeofilter AST) to a DuckDB WHERE clause.

pygeoapi parses the ``filter`` parameter and hands providers a
pygeofilter AST, so this module only compiles it. `DuckDBSQLEvaluator`
derives from pygeofilter's ``SQLEvaluator``, whose spatial function
names already match DuckDB's, and departs from it in six places:

String literals
    Upstream writes them between quotes as they are, so a quote in the
    value ends the SQL string. The evaluator doubles the quotes.
Geometry and envelope literals
    Upstream writes ``ST_GeomFromWKB(x'<hex>')``. In DuckDB ``x'…'`` is a
    bit-string literal and the call fails with "Unsupported geometry type
    in WKB", so the evaluator writes ``ST_GeomFromHEXWKB('<hex>')``.
Datetime literals
    Upstream writes anything that is not a string with ``str()``, and
    DuckDB rejects a bare datetime. The evaluator quotes its ISO form.
Temporal operators
    Upstream's ``temporal`` handler is commented out, so every ``T_*``
    node raises ``NotImplementedError``. The evaluator writes ``AFTER``,
    ``BEFORE`` and ``TEQUALS`` on instants and refuses the others.
``CASEI`` and ``ACCENTI``
    Upstream looks functions up in a map that is empty here, and its
    ``like`` handler takes the pattern as a plain string, so
    ``CASEI(name) LIKE CASEI('%x%')`` fails. The evaluator writes
    ``lower`` and ``strip_accents``, in patterns too.
Properties that are not queryables
    Upstream raises ``KeyError``. The queryables leave
    ``additionalProperties`` unset, so such a property is null
    (/req/queryables/get-queryables-response, G) and the evaluator
    writes ``NULL``.

`find_filter_envelope` gives the envelope that the bboxes of the matches
of a filter overlap, so a provider can choose files and row groups for a
spatial filter as it does for ``bbox``.
"""

from __future__ import annotations

from datetime import date, datetime, time

import shapely.geometry
from pygeofilter import ast, values
from pygeofilter.backends.evaluator import handle
from pygeofilter.backends.sql.evaluate import SQLEvaluator


class UnsupportedFilterError(Exception):
    """The filter names something this provider cannot serve."""


# CQL2 functions → DuckDB functions. pygeofilter parses CASEI as ``lower``
# and ACCENTI as ``accenti`` (/req/case-insensitive-comparison,
# /req/accent-insensitive-comparison).
_FUNCTION_MAP = {
    "lower": "lower",
    "accenti": "strip_accents",
}


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

    @handle(ast.Attribute)
    def attribute(self, node: ast.Attribute) -> str:
        """Write the column of a property, or ``NULL`` for one that is not a queryable.

        Parameters
        ----------
        node
            The property the filter names.

        Returns
        -------
        str
            The quoted column, or ``NULL``. The name of a property outside
            the mapping never reaches the SQL.
        """
        column = self.attribute_map.get(node.name)
        if column is None:
            return "NULL"
        return f'"{column}"'

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

    @handle(ast.Function)
    def function(self, node, *arguments) -> str:
        """Write the DuckDB call of a CQL2 function.

        Parameters
        ----------
        node
            The function node, named as pygeofilter parses it: ``lower``
            for ``CASEI``, ``accenti`` for ``ACCENTI``.
        *arguments
            The arguments, already written as SQL.

        Returns
        -------
        str
            The SQL call, such as ``lower("name")``.

        Raises
        ------
        UnsupportedFilterError
            For a function this provider does not know; the route answers
            400.
        """
        try:
            func = self.function_map[node.name]
        except KeyError as e:
            raise UnsupportedFilterError(
                f"function {node.name} is not supported by this provider"
            ) from e
        return f"{func}({','.join(arguments)})"

    @handle(ast.Like)
    def like(self, node, lhs) -> str:
        """Write a LIKE with its pattern escaped the same way as any literal.

        The base implementation interpolates ``node.pattern`` directly,
        which is the same injection vector as :meth:`literal`.

        Parameters
        ----------
        node
            The LIKE node, with its pattern and its wildcard characters.
        lhs
            The left side, already written as SQL.

        Returns
        -------
        str
            The SQL condition, such as ``lower("name") LIKE lower('%x%')``.
        """
        operator = "ILIKE" if node.nocase and self.use_ilike else "LIKE"
        negation = "NOT " if node.not_ else ""
        pattern = self._write_like_pattern(node, node.pattern)
        return f"{lhs} {negation}{operator} {pattern} ESCAPE '{node.escapechar}'"

    def _write_like_pattern(self, node, pattern) -> str:
        """Write a LIKE pattern as SQL: a quoted string, or functions of one.

        Parameters
        ----------
        node
            The LIKE node, whose wildcard characters become ``%`` and ``_``.
        pattern
            The pattern, as a string or as a function of one, such as
            ``CASEI('%cave%')``.

        Returns
        -------
        str
            The escaped pattern, wrapped in its functions.

        Raises
        ------
        UnsupportedFilterError
            When the pattern is neither a string nor a function of one.
        """
        if isinstance(pattern, ast.Function):
            inner = ",".join(
                self._write_like_pattern(node, argument) for argument in pattern.arguments
            )
            return self.function(pattern, inner)
        if not isinstance(pattern, str):
            raise UnsupportedFilterError("a LIKE pattern must be a string")
        if node.wildcard != "%":
            pattern = pattern.replace(node.wildcard, "%")
        if node.singlechar != "_":
            pattern = pattern.replace(node.singlechar, "_")
        return "'" + pattern.replace("'", "''") + "'"


def to_duckdb_where(root, field_mapping: dict[str, str]) -> str:
    """Compile a pygeofilter AST into a DuckDB WHERE clause.

    A function or an operator this provider cannot serve raises
    `UnsupportedFilterError` from the evaluator. A property outside
    ``field_mapping`` is written as ``NULL``.

    Parameters
    ----------
    root
        The filter as pygeoapi parses it, from CQL2 text or JSON.
    field_mapping
        The queryable properties and their columns. It is also the
        allowlist of identifiers: a property outside it never reaches SQL.

    Returns
    -------
    str
        The WHERE condition, without the keyword.
    """
    return DuckDBSQLEvaluator(field_mapping, _FUNCTION_MAP).evaluate(root)


# A match of every spatial comparison but DISJOINT shares at least one point
# with the literal geometry, so its envelope overlaps the literal's envelope.
_OVERLAPPING_OPS = frozenset(ast.SpatialComparisonOp) - {ast.SpatialComparisonOp.DISJOINT}

Bounds = tuple[float, float, float, float]


def find_filter_envelope(root, geometry_column: str) -> Bounds | None:
    """Find an envelope that the bbox of every match of a filter overlaps.

    Only the spatial predicates on ``geometry_column`` that every match
    satisfies count: the filter itself, or a term of a chain of ``AND``.
    For the filter::

        name = 'Roma'
        AND S_INTERSECTS(geom, POLYGON((0 0, 4 0, 4 4, 0 4, 0 0)))
        AND S_WITHIN(geom, POLYGON((2 2, 6 2, 6 6, 2 6, 2 2)))

    ``name = 'Roma'`` bounds nothing, the first polygon gives
    ``(0, 0, 4, 4)``, the second ``(2, 2, 6, 6)``, and the envelope is
    their overlap ``(2, 2, 4, 4)``. A geometry can meet both polygons and
    still miss the overlap: the line from (1, 1) up to (1, 5) and across
    to (5, 5) does. Its bbox always meets the overlap, though, and the
    file index and the covering column hold bboxes. When the two envelopes
    do not overlap, nothing matches and the first one is returned.

    With ``OR`` in place of both ``AND`` the result is ``None``, since a
    feature named Roma can lie anywhere. ``NOT``, ``S_DISJOINT``,
    the distance and relate predicates and a ``BBOX`` with its own CRS
    give ``None`` as well.

    Parameters
    ----------
    root
        The filter as pygeoapi parses it, from CQL2 text or JSON.
    geometry_column
        The column the spatial predicates must name.

    Returns
    -------
    tuple[float, float, float, float] or None
        ``(minx, miny, maxx, maxy)``, or ``None`` when the filter does not
        bound the features it matches.
    """
    if isinstance(root, ast.And):
        envelopes = [
            envelope
            for envelope in (
                find_filter_envelope(root.lhs, geometry_column),
                find_filter_envelope(root.rhs, geometry_column),
            )
            if envelope is not None
        ]
        if len(envelopes) < 2:
            return envelopes[0] if envelopes else None
        (aminx, aminy, amaxx, amaxy), (bminx, bminy, bmaxx, bmaxy) = envelopes
        overlap = (max(aminx, bminx), max(aminy, bminy), min(amaxx, bmaxx), min(amaxy, bmaxy))
        if overlap[0] > overlap[2] or overlap[1] > overlap[3]:
            # No feature can match both; either envelope still bounds the matches.
            return envelopes[0]
        return overlap
    if isinstance(root, ast.BBox):
        if root.crs is not None or not _names_column(root.lhs, geometry_column):
            return None
        return (root.minx, root.miny, root.maxx, root.maxy)
    if isinstance(root, ast.SpatialComparisonPredicate) and root.op in _OVERLAPPING_OPS:
        for column, literal in ((root.lhs, root.rhs), (root.rhs, root.lhs)):
            if _names_column(column, geometry_column):
                return _bound_literal(literal)
    return None


def _names_column(node, geometry_column: str) -> bool:
    """Check that a predicate operand is the geometry column.

    Parameters
    ----------
    node
        An operand of a spatial predicate.
    geometry_column
        The name of the geometry column.

    Returns
    -------
    bool
        Whether ``node`` is the attribute ``geometry_column``.
    """
    return isinstance(node, ast.Attribute) and node.name == geometry_column


def _bound_literal(node) -> Bounds | None:
    """Bound a geometry or envelope literal.

    Parameters
    ----------
    node
        An operand of a spatial predicate.

    Returns
    -------
    tuple[float, float, float, float] or None
        ``(minx, miny, maxx, maxy)`` of the literal, or ``None`` when
        ``node`` is not a literal.
    """
    if isinstance(node, values.Envelope):
        box = shapely.geometry.box(node.x1, node.y1, node.x2, node.y2)
    elif isinstance(node, values.Geometry):
        box = shapely.geometry.shape(node)
    else:
        return None
    return box.bounds
