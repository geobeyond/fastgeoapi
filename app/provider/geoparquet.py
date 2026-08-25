"""Read-only GeoParquet provider on a DuckDB engine (ADR-0004).

Multi-cloud by construction: the source is a local path or a bucket URL
and the engine reads it through the same session helper. CQL2 filters —
spatial predicates included — are compiled to SQL and evaluated in the
engine, and features leave it as GeoJSON, so no dataframe library sits
in the serving path.

Configure it by dotted path::

    providers:
      - type: feature
        name: app.provider.geoparquet.GeoParquetProvider
        data: s3://bucket/tenants/acme/lakes
        id_field: id
        geometry_column: geom
        time_field: ts
"""

from __future__ import annotations

from pygeoapi.provider.base import BaseProvider, ProviderQueryError

from app.config.logging import create_logger
from app.provider.duckdb_ import connect, scan_expression

logger = create_logger("app.provider.geoparquet")

# DuckDB type prefix → (JSON Schema type, format). Prefix matching keeps
# parameterised types (DECIMAL(18,3), TIMESTAMP WITH TIME ZONE) covered.
_TYPE_MAP: tuple[tuple[str, tuple[str, str | None]], ...] = (
    ("BOOLEAN", ("boolean", None)),
    ("TINYINT", ("integer", None)),
    ("SMALLINT", ("integer", None)),
    ("INTEGER", ("integer", None)),
    ("BIGINT", ("integer", None)),
    ("HUGEINT", ("integer", None)),
    ("UBIGINT", ("integer", None)),
    ("UINTEGER", ("integer", None)),
    ("FLOAT", ("number", None)),
    ("DOUBLE", ("number", None)),
    ("DECIMAL", ("number", None)),
    ("TIMESTAMP", ("string", "date-time")),
    ("DATE", ("string", "date")),
    ("TIME", ("string", "time")),
)


class GeoParquetProvider(BaseProvider):
    """OGC API Features provider for GeoParquet on object storage.

    Declares ``THREAD_SAFE`` so one instance is reused process-wide
    instead of being rebuilt per request: every operation takes its own
    DuckDB cursor, which is that engine's documented pattern for
    concurrent use (see :meth:`_cursor`).

    On SQL construction: every identifier interpolated below comes from
    the dataset's own schema (``self._types``, read via ``DESCRIBE``) or
    from the provider configuration, and is rejected when it is not —
    request text never becomes an identifier. Values are either bound as
    parameters (``get``) or quote-escaped, and CQL2 goes through
    :mod:`app.provider.cql2_duckdb`, whose field mapping is the
    allowlist. The suppressions below mark that reasoning; they are
    not a shrug.
    """

    #: Opt into the process-wide plugin cache (app/pygeoapi/plugin.py).
    THREAD_SAFE = True

    def __init__(self, provider_def):
        """Open the engine and read the dataset schema once."""
        super().__init__(provider_def)
        if not self.id_field:
            raise ProviderQueryError("id_field is required by the GeoParquet provider")
        self.geometry_column = provider_def.get("geometry_column", "geom")
        self._configured_covering = provider_def.get("bbox_column")
        self._scan = scan_expression(self.data, store_options=provider_def.get("store_options"))
        # Per-dataset store options (region, skip_signature for public
        # data, endpoint for an S3-compatible service) travel with the
        # provider definition — credentials themselves stay in the
        # standard environment variables.
        self._connection = connect(
            self.data,
            store_options=provider_def.get("store_options"),
            engine_options=provider_def.get("engine_options"),
        )
        self._types = self._describe()
        if self.geometry_column not in self._types:
            raise ProviderQueryError(
                f"geometry column '{self.geometry_column}' is not in the dataset "
                f"(columns: {', '.join(sorted(self._types))})"
            )
        self.covering_bbox_column = self._detect_covering_bbox_column()
        # Populate the fields eagerly: ``BaseProvider.__init__`` already
        # sets ``_fields = {}``, so the ``fields`` property returns that
        # empty dict instead of falling back to ``get_fields()`` — and
        # /queryables reads the property. Upstream's own ParquetProvider
        # carries the same call for the same reason.
        self.get_fields()

    def _cursor(self):
        """A cursor for one operation.

        pygeoapi drives providers from a threadpool, and a single DuckDB
        connection shared across threads loses results: one thread's
        ``execute`` resets another's pending result, so ``fetchone``
        returns None and a fraction of concurrent requests answer wrong
        (measured: 4 of 24 with 6 workers). ``cursor()`` is DuckDB's
        documented pattern for concurrent use — it shares the database
        while keeping the result state per operation.
        """
        return self._connection.cursor()

    def _describe(self) -> dict[str, str]:
        """Column name → DuckDB type, straight from the dataset schema."""
        # `_scan` is derived from the provider definition's `data`, never
        # from request input, and nothing else is interpolated here.
        # ruff: ignore[hardcoded-sql-expression]
        describe_sql = f"DESCRIBE SELECT * FROM {self._scan}"  # nosec B608
        rows = self._cursor().execute(describe_sql).fetchall()
        return {row[0]: str(row[1]).upper() for row in rows}

    def _detect_covering_bbox_column(self) -> str | None:
        """The GeoParquet covering column, when the dataset carries one.

        A covering is a struct of xmin/xmax/ymin/ymax doubles that mirrors
        each geometry's envelope. Unlike a spatial predicate it carries
        row-group statistics, so a filter expressed on it lets DuckDB skip
        row groups outright — measured on a 578 MB Overture file over S3,
        19s against 64s for the same window.
        """
        if self._configured_covering:
            if self._configured_covering not in self._types:
                raise ProviderQueryError(
                    f"bbox_column '{self._configured_covering}' is not in the dataset"
                )
            return self._configured_covering
        for name, duckdb_type in self._types.items():
            if name == self.geometry_column or not duckdb_type.startswith("STRUCT"):
                continue
            lowered = duckdb_type.lower()
            if all(key in lowered for key in ("xmin", "xmax", "ymin", "ymax")):
                return name
        return None

    def _geometry_expression(self) -> str:
        """The SQL expression yielding a geometry for the geometry column.

        DuckDB hands back a GEOMETRY for files it wrote itself, while a
        third-party GeoParquet arrives as a WKB BLOB that needs an
        explicit conversion.
        """
        column = f'"{self.geometry_column}"'
        if self._types.get(self.geometry_column, "").startswith("GEOMETRY"):
            return column
        return f"ST_GeomFromWKB({column})"

    def get_fields(self) -> dict:
        """Queryable properties and their JSON Schema types."""
        if not self._fields:
            for name, duckdb_type in self._types.items():
                # The geometry and its covering are storage detail, not
                # properties a client queries or receives.
                if name in (self.geometry_column, self.covering_bbox_column):
                    continue
                json_type, json_format = "string", None
                for prefix, mapped in _TYPE_MAP:
                    if duckdb_type.startswith(prefix):
                        json_type, json_format = mapped
                        break
                field: dict[str, str] = {"type": json_type}
                if json_format is not None:
                    field["format"] = json_format
                self._fields[name] = field
        return self._fields

    def _select_columns(self, select_properties: list[str]) -> list[str]:
        """Property columns to return, honouring config and request."""
        available = [
            name
            for name in self._types
            if name not in (self.geometry_column, self.covering_bbox_column)
        ]
        if select_properties:
            unknown = set(select_properties) - set(available)
            if unknown:
                raise ProviderQueryError(f"unknown properties: {', '.join(sorted(unknown))}")
            return list(select_properties)
        if self.properties:
            return [name for name in self.properties if name in available]
        return available

    def _order_by(self, sortby: list[dict]) -> str:
        """ORDER BY clause from pygeoapi's sortby structure."""
        if not sortby:
            return ""
        parts = []
        for item in sortby:
            column = item["property"]
            if column not in self._types:
                raise ProviderQueryError(f"cannot sort by unknown property: {column}")
            direction = "DESC" if item.get("order") in ("-", "DESC", "desc") else "ASC"
            parts.append(f'"{column}" {direction}')
        return " ORDER BY " + ", ".join(parts)

    def _bbox_clause(self, bbox: list) -> str:
        """Intersection against the request bbox, evaluated in-engine.

        With a covering column the clause gains an envelope-overlap
        pre-filter on it. That test is a superset of the real one — a
        bbox can overlap where the geometry does not — so the exact
        ``ST_Intersects`` stays and decides. What the pre-filter buys is
        row-group pruning, which a spatial predicate cannot do.
        """
        minx, miny, maxx, maxy = (float(value) for value in bbox[:4])
        envelope = f"ST_MakeEnvelope({minx}, {miny}, {maxx}, {maxy})"
        exact = f"ST_Intersects({self._geometry_expression()}, {envelope})"
        covering = self.covering_bbox_column
        if covering is None:
            return exact
        column = f'"{covering}"'
        overlap = (
            f"{column}.xmin <= {maxx} AND {column}.xmax >= {minx} AND "
            f"{column}.ymin <= {maxy} AND {column}.ymax >= {miny}"
        )
        return f"({overlap} AND {exact})"

    def _datetime_clause(self, datetime_: str) -> str:
        """Instant or interval on ``time_field`` (RFC 3339, '..' open ends)."""
        if not self.time_field:
            raise ProviderQueryError(
                "datetime filtering needs time_field in the provider configuration"
            )
        column = f'"{self.time_field}"'
        if "/" not in datetime_:
            return f"{column} = '{datetime_}'"
        start, _, end = datetime_.partition("/")
        bounds = []
        if start not in ("..", ""):
            bounds.append(f"{column} >= '{start}'")
        if end not in ("..", ""):
            bounds.append(f"{column} <= '{end}'")
        if not bounds:
            raise ProviderQueryError(f"unbounded datetime interval: {datetime_}")
        return "(" + " AND ".join(bounds) + ")"

    def _where_clauses(self, bbox, datetime_, properties, filterq) -> list[str]:
        """SQL predicates for every supported filter, CQL2 included."""
        clauses: list[str] = []
        for name, value in properties:
            if name not in self._types:
                raise ProviderQueryError(f"unknown property: {name}")
            escaped = str(value).replace("'", "''")
            clauses.append(f"\"{name}\" = '{escaped}'")
        if bbox:
            clauses.append(self._bbox_clause(bbox))
        if datetime_:
            clauses.append(self._datetime_clause(datetime_))
        if filterq is not None:
            from app.provider.cql2_duckdb import UnsupportedFilterError, to_duckdb_where

            mapping = {name: name for name in self._types}
            try:
                clauses.append(to_duckdb_where(filterq, mapping))
            except UnsupportedFilterError as e:
                raise ProviderQueryError(str(e)) from e
        return clauses

    def _rows_to_features(self, rows, columns: list[str], skip_geometry: bool) -> list[dict]:
        """Assemble GeoJSON features from the engine's own output."""
        import json

        features = []
        for row in rows:
            record = dict(zip([*columns, "__geometry__"], row, strict=True))
            geometry_json = record.pop("__geometry__")
            identifier = record.get(self.id_field)
            properties = {k: v for k, v in record.items() if k != self.id_field}
            features.append(
                {
                    "type": "Feature",
                    "id": identifier,
                    "geometry": None
                    if skip_geometry or geometry_json is None
                    else json.loads(geometry_json),
                    "properties": properties,
                }
            )
        return features

    def query(
        self,
        offset=0,
        limit=10,
        resulttype="results",
        bbox=None,
        datetime_=None,
        properties=None,
        sortby=None,
        skip_geometry=False,
        select_properties=None,
        crs_transform_spec=None,
        q=None,
        language=None,
        filterq=None,
        **kwargs,
    ) -> dict:
        """Query the dataset, pushing every supported filter into DuckDB."""
        where = self._where_clauses(
            bbox=bbox or [],
            datetime_=datetime_,
            properties=properties or [],
            filterq=filterq,
        )
        clause = f" WHERE {' AND '.join(where)}" if where else ""

        # `clause` never carries raw request input: CQL2 properties pass
        # through `field_mapping`, which doubles as an identifier allowlist,
        # and our dialect escapes quotes in literals and LIKE patterns;
        # bbox and datetime emit numeric or quoted values.
        # ruff: ignore[hardcoded-sql-expression]
        count_sql = f"SELECT count(*) FROM {self._scan}{clause}"  # nosec B608
        # Counting a remote dataset is not free: 15s on the Overture file.
        # `count: false` in the provider definition drops it, exactly as
        # upstream's SQL provider does — a hits request always counts,
        # since that number is the whole answer.
        matched = None
        if self.count or resulttype == "hits":
            matched = self._cursor().execute(count_sql).fetchone()[0]
        if resulttype == "hits":
            return {
                "type": "FeatureCollection",
                "features": [],
                "numberMatched": matched,
                "numberReturned": 0,
            }

        columns = self._select_columns(select_properties or [])
        if self.id_field not in columns:
            columns = [self.id_field, *columns]
        projection = ", ".join(f'"{name}"' for name in columns)
        geometry = "NULL" if skip_geometry else f"ST_AsGeoJSON({self._geometry_expression()})"
        # `projection` quotes column names taken from the dataset schema,
        # `clause` is built as described in `_where_clauses`, and the paging
        # values are cast to int before they reach the string.
        sql = (
            # ruff: ignore[hardcoded-sql-expression]
            f"SELECT {projection}, {geometry} FROM {self._scan}{clause}"  # nosec B608
            f"{self._order_by(sortby or [])} LIMIT {int(limit)} OFFSET {int(offset)}"
        )
        logger.debug(f"GeoParquet query: {sql}")
        rows = self._cursor().execute(sql).fetchall()
        features = self._rows_to_features(rows, columns, skip_geometry)
        collection = {
            "type": "FeatureCollection",
            "features": features,
            "numberReturned": len(features),
        }
        if matched is not None:
            collection["numberMatched"] = matched
        return collection

    def get(self, identifier, **kwargs) -> dict:
        """Fetch a single feature by its identifier.

        The identifier is bound as a parameter and compared as text, so
        a numeric or string id both work and nothing from the URL ever
        reaches the SQL text.
        """
        from pygeoapi.provider.base import ProviderItemNotFoundError

        columns = self._select_columns([])
        if self.id_field not in columns:
            columns = [self.id_field, *columns]
        projection = ", ".join(f'"{name}"' for name in columns)
        # The identifier itself is bound as a parameter, not interpolated;
        # only schema-derived column names reach the string.
        sql = (
            # ruff: ignore[hardcoded-sql-expression]
            f"SELECT {projection}, ST_AsGeoJSON({self._geometry_expression()}) "  # nosec B608
            f'FROM {self._scan} WHERE CAST("{self.id_field}" AS VARCHAR) = ? LIMIT 1'
        )
        rows = self._cursor().execute(sql, [str(identifier)]).fetchall()
        if not rows:
            raise ProviderItemNotFoundError(f"no such item: {identifier}")
        return self._rows_to_features(rows, columns, skip_geometry=False)[0]
