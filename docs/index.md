---
title: fastgeoapi
icon: material/home
---

<p align="center">
  <img src="images/lockup-stacked.svg" width="260" alt="fastgeoapi" />
</p>

**An OGC API for data that is already cloud-native.** Your GeoParquet,
your PMTiles, your COG sit in a bucket, and something still needs a
standard API in front of them: QGIS, a browser, a partner, an agent.
fastgeoapi serves one straight from those formats, where they are, with
[pygeoapi](https://pygeoapi.io) as the engine — and because reading them
means ranged requests over the network, it awaits those reads instead of
parking a thread on each.

<div class="grid cards" markdown>

- **Cloud-native formats, in place**

    GeoParquet queried by DuckDB and PMTiles read by byte range, from S3,
    GCS, Azure or Tigris. No load into a database, no pre-cut tile tree,
    no second copy — and the configuration can live in the same bucket.

    [GeoParquet provider](operators/how-to/geoparquet.md) ·
    [PMTiles provider](operators/how-to/pmtiles.md) ·
    [Config from cloud storage](operators/how-to/cloud-config.md)

- **Async where waiting is the cost**

    A ranged read is a round trip, and a map view asks for fifty at once.
    Those are awaited together rather than five at a time on a thread
    pool — with a guard in the test suite that fails if the loop blocks.

    [Two faces for a provider](contributors/explanation/async-providers.md)

- **Standard, and only what you configured**

    OGC API — Features, Tiles, Processes, Records, EDR and STAC, from
    pygeoapi unchanged. The route table and `/conformance` are built from
    your resources, so they describe this server rather than the
    catalogue.

    [Why fastgeoapi](operators/explanation/why-fastgeoapi.md)

- **Behind authentication, and usable by agents**

    OAuth2 with JWKS, an API key or Open Policy Agent in front; an MCP
    endpoint with its own authorization server behind, so a client like
    Claude can query your collections as tools.

    [Getting started](operators/tutorials/getting-started.md) ·
    [MCP server](consumers/index.md)

</div>

## Where to start

If you are **standing a server up**, read
[Getting started](operators/tutorials/getting-started.md) and then the
[configuration reference](operators/reference/configuration.md).

If you are **changing a configuration that already runs**, the
[editor](operators/how-to/configuration-editor.md) will tell you whether it builds before
you save it.

If you are **connecting an agent**, start at
[MCP getting started](consumers/tutorials/connecting-an-mcp-client.md).

## Live demo

A running instance is at
[fastgeoapi.fly.dev](https://fastgeoapi.fly.dev/geoapi), on one vCPU in
Paris. Four of its collections are cloud-native formats served in place:
Overture Maps places, as GeoParquet and as an 18 GB PMTiles archive, both
read where Overture publishes them in `us-west-2`; and a Lazio road
extract in the same two shapes, staged in a bucket beside the server —
the pair that shows what locality is worth. Its
[OpenAPI document](consumers/reference/openapi.md) is published here, and
[Using fastgeoapi from QGIS](consumers/tutorials/using-qgis.md) puts two
of those collections on a map.

## Installation

```bash
pip install fastgeoapi
fastgeoapi run
```

The full instructions — including the authentication options, which are
the part worth reading — are in
[Getting started](operators/tutorials/getting-started.md).
