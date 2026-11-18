---
name: ogcapi-tiles
description: Describe the tiles of a collection with OGC API - Tiles, and build tile addresses for a map client. Use it when a client will render the data, not to read features.
---

# Working with tiles

Tiles cut a collection into a pyramid of small pieces, so a map client
can draw any area at any zoom quickly. They suit a client that renders.
To read attributes use features; to see one area as an image use maps.

## The tilesets

`GET /collections/{collectionId}/tiles` lists the tilesets of the
collection. Each one names the grid its tiles follow, the tile matrix
set, with a `tileMatrixSetURI` such as
`http://www.opengis.net/def/tilematrixset/OGC/1.0/WebMercatorQuad`; the
last segment, `WebMercatorQuad`, is its id. Its `dataType` says `vector`
for vector tiles or `map` for images.

The list, or each tileset, has a link whose `rel` is `item` and whose
`href` is the template of the tile addresses, with
`{tileMatrix}`, `{tileRow}` and `{tileCol}` to fill in.

`GET /collections/{collectionId}/tiles/{tileMatrixSetId}` describes one
tileset. When it has `tileMatrixSetLimits`, they give, for each zoom
level (`tileMatrix`), the first and last row and column that hold data.

## Tile addresses

A tile is at
`/collections/{collectionId}/tiles/{tileMatrixSetId}/{tileMatrix}/{tileRow}/{tileCol}`.
In `WebMercatorQuad` the `tileMatrix` is the zoom level, the `tileRow`
is the `y` of the usual `z/x/y` scheme and the `tileCol` is the `x`. So
`z/x/y` becomes `{tileMatrix}/{tileRow}/{tileCol}` = `z/y/x`.

Give the template to the map client rather than fetching tiles one by
one. Vector tiles are binary (Mapbox Vector Tile); they are not meant to
be read as text.

## When something looks wrong

- **A 404 on a tile.** The row or the column is outside the grid at that
  zoom level, or the row and the column are swapped. When the tileset
  has `tileMatrixSetLimits`, check them.
- **Tiles in the wrong place.** The client uses `z/x/y` while the
  address wants row, then column.
- **An empty tile.** There is no data in that piece of the grid; try a
  tile inside the `extent` of the collection.
