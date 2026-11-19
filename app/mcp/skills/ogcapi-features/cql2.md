# Filtering features with CQL2

Add a CQL2 expression to `GET /collections/{collectionId}/items` with
three parameters from OGC API - Features Part 3:

- `filter`: the expression.
- `filter-lang`: `cql2-text` (the default) or `cql2-json`.
- `filter-crs`: the CRS of the geometries in the expression. Without
  it they are in CRS84, longitude first.

The filter combines with `bbox`, `datetime`, `limit` and the other
parameters. The `next` link of a page keeps it.

## Property names

Take them from the queryables of the collection. In CQL2 text a bare
name is a property and a single quoted string is a value: `class = 'primary'`. In CQL2 JSON a property is `{"property": "class"}`.

## Operators

| Kind          | CQL2 text                                                                             | CQL2 JSON `op`      |
| ------------- | ------------------------------------------------------------------------------------- | ------------------- |
| comparison    | `=`, `<>`, `<`, `<=`, `>`, `>=`                                                       | the same symbols    |
| pattern       | `name LIKE 'Via%'` (`%` any text, `_` one character)                                  | `like`              |
| list          | `class IN ('primary', 'secondary')`                                                   | `in`                |
| range         | `depth BETWEEN 10 AND 20`                                                             | `between`           |
| missing value | `name IS NULL`                                                                        | `isNull`            |
| logic         | `AND`, `OR`, `NOT`, parentheses                                                       | `and`, `or`, `not`  |
| spatial       | `S_INTERSECTS(geometry, POLYGON((...)))`, also `S_WITHIN`, `S_CONTAINS`, `S_DISJOINT` | `s_intersects`, ... |
| case, accents | `CASEI(name) LIKE CASEI('%cave%')`, `ACCENTI(name) = ACCENTI('citta')`                | `casei`, `accenti`  |

For dates, use the `datetime` parameter of the items: servers differ in
the temporal operators they accept.

Geometries are WKT in CQL2 text and GeoJSON in CQL2 JSON. The geometry
property is the one the queryables describe as a geometry.

Text comparisons match case and accents exactly: `'Via'` does not find
`'VIA'`. Wrap both sides in `CASEI` to ignore case and in `ACCENTI` to
ignore accents. They belong to the conformance classes
`case-insensitive-comparison` and `accent-insensitive-comparison`, and a
server without them refuses the filter.

## Examples

The same filter in both encodings, roads of class primary inside a box
around Rome:

```text
filter=class = 'primary' AND S_INTERSECTS(geometry, POLYGON((12.3 41.8, 12.6 41.8, 12.6 42.0, 12.3 42.0, 12.3 41.8)))
```

```text
filter-lang=cql2-json
filter={"op": "and", "args": [
  {"op": "=", "args": [{"property": "class"}, "primary"]},
  {"op": "s_intersects", "args": [{"property": "geometry"},
    {"type": "Polygon", "coordinates": [[[12.3, 41.8], [12.6, 41.8], [12.6, 42.0], [12.3, 42.0], [12.3, 41.8]]]}]}
]}
```

## When something looks wrong

- **A 400 answer.** The expression does not parse, or it is not a
  condition: a property or a value alone is not a filter. Check the
  quotes in CQL2 text and that every `op` has its `args`.
- **A 400 on `between` in CQL2 JSON.** Some servers take the two
  bounds as one array, `[10, 20]`. The text form `depth BETWEEN 10 AND 20`
  works on both.
- **No features.** WKT and GeoJSON put longitude first unless
  `filter-crs` says otherwise. A polygon must close on its first point.
  A text value may differ only in case or accents: try `CASEI` and
  `ACCENTI`, or look at a few features to see how values are written.
- **A server error on a property.** The name may not be a queryable.
  Take it from the queryables, with the same case.
