---
name: ogcapi-features
description: Read the features of a collection with OGC API - Features. Use it to list, filter, sort and page through items, or to get one item by id.
---

# Reading features

The features of a collection are at `GET /collections/{collectionId}/items`.
One feature is at `GET /collections/{collectionId}/items/{featureId}`. Both
answer GeoJSON.

## Before filtering, read the queryables

`GET /collections/{collectionId}/queryables` answers a JSON Schema. Its
`properties` are the names you can filter and sort on, with their types.
Use those names exactly; they are case sensitive.

## Narrowing the result

- `bbox`: four numbers, `minLon,minLat,maxLon,maxLat`, longitude first.
  Six numbers add a minimum and maximum height. The coordinates are in
  CRS84 unless `bbox-crs` names another CRS, in which case they follow
  that CRS's axis order.
- `datetime`: an instant, `2024-05-01T10:00:00Z`, or an interval,
  `2024-05-01T00:00:00Z/2024-05-31T23:59:59Z`. Use `..` for an open end:
  `2024-05-01T00:00:00Z/..`.
- A queryable given as a parameter, `name=value`, keeps the features
  whose property equals that value exactly.
- For anything richer, a comparison, a pattern, a spatial or temporal
  test, use a CQL2 filter. Read `cql2.md` in this skill. The server
  offers it only on collections whose data source applies the filter;
  without it, a filter is not available there.

## Shaping the answer

- `properties`: a comma separated list of the properties to return,
  `name,class`.
- `skipGeometry`: `true` drops the geometries when you need only the
  attributes. The answers get much smaller.
- `sortby`: a comma separated list of properties, each with `+` or `-`
  for ascending or descending, `-population,+name`.

## Paging

`limit` sets how many features a page holds; the server may cap it. The
answer says `numberReturned` for this page and, when it knows,
`numberMatched` for all pages. To get the next page, follow the link
whose `rel` is `next`: it carries every parameter of the request, the
filter included. Do not compute the offset yourself. When there is no
`next` link, you have every feature.

Keep `limit` small while exploring.

## When something looks wrong

- **No features, and you expected some.**
  - The bbox may have its axes swapped. Longitude comes first: a box
    around Rome is `12.3,41.8,12.6,42.0`.
  - The bbox or the datetime may fall outside the `extent` of the
    collection. Compare them.
  - A property name may not be a queryable, or may differ in case.
- **A 400 answer.** A parameter is malformed, for example a bbox with
  three numbers or a datetime the server cannot read. The message usually
  says which.
- **Far fewer features than `numberMatched`.** That is one page. Follow
  the `next` link.
