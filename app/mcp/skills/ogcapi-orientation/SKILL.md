---
name: ogcapi-orientation
description: Find out what an OGC API server offers before using it. Read this first, then the skill for features, processes, maps or tiles.
---

# Finding your way around an OGC API

An OGC API is a set of resources linked to each other. Start from three
of them and follow the links, instead of guessing paths.

## The three starting points

- `/` is the landing page. Its `links` point to everything else: the API
  definition, the conformance declaration, the collections, the
  processes.
- `/conformance` lists the conformance classes the server implements, as
  URIs. They say which standards and which options you can rely on, for
  example `.../ogcapi-features-1/1.0/conf/core` for features or
  `.../ogcapi-processes-1/1.0/conf/core` for processes.
- `/collections` lists the collections, each with an `id`, a title, a
  description, its spatial and temporal `extent`, and its links.

Ask for JSON with the parameter `f`: `f=json`. Without it some servers
answer HTML.

## Reading a collection

The links of a collection say what you can do with it. Match them by
`rel`, not by position:

| `rel`                                                                          | What it leads to                 | Read next         |
| ------------------------------------------------------------------------------ | -------------------------------- | ----------------- |
| `items`                                                                        | the features of the collection   | `ogcapi-features` |
| `http://www.opengis.net/def/rel/ogc/1.0/queryables`                            | the properties you can filter on | `ogcapi-features` |
| `http://www.opengis.net/def/rel/ogc/1.0/map`                                   | a rendered map                   | `ogcapi-maps`     |
| `http://www.opengis.net/def/rel/ogc/1.0/tilesets-vector` or `.../tilesets-map` | tiles                            | `ogcapi-tiles`    |

Processes are not collections. They are listed at `/processes`; read
`ogcapi-processes` before running one.

The `extent` of a collection tells you where and when there is data. Use
it to choose an area or a time that can match something.

## When something looks wrong

- **An empty list or a 404.** The collection id is case sensitive and
  comes from `/collections`. Take it from there, do not build it from a
  title.
- **HTML instead of JSON.** Add `f=json`.
- **A feature you expected is missing from the conformance list.** The
  server does not implement it; do not try the operation anyway.
- **Coordinates that land in the wrong place.** Unless a CRS is given,
  coordinates are longitude first, then latitude (CRS84). A box around
  Rome is `12.3,41.8,12.6,42.0`, not `41.8,12.3,42.0,12.6`.
