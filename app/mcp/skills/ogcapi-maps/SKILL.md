---
name: ogcapi-maps
description: Get a rendered map image of a collection with OGC API - Maps. Use it to see an area, choosing the box and the size in pixels.
---

# Getting a map

`GET /collections/{collectionId}/map` answers an image of the
collection, rendered by the server. A collection with styles may also
offer `GET /collections/{collectionId}/styles/{styleId}/map`.

## Choosing the area and the size

- `bbox`: `minLon,minLat,maxLon,maxLat`, longitude first, in CRS84. A
  box around Rome is `12.3,41.8,12.6,42.0`. Take it inside the `extent`
  of the collection.
- `width` and `height`: the size of the image in pixels. Keep the ratio
  of the box, or the map comes out stretched. A server may refuse sizes
  above its maximum.

The collection's links list the image formats the server renders, by
media type, such as `image/png`.

## When something looks wrong

- **A blank or transparent image.** The box is outside the data. Compare
  it with the `extent` of the collection, and check that longitude comes
  first.
- **A distorted image.** `width` and `height` do not keep the ratio of
  the box.
- **A 400 answer.** The size is above the server's maximum, or the box
  has its minimum above its maximum.
