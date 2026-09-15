---
icon: material/handshake-outline
---

# :material-handshake-outline: Interoperability notes

You are pointing your own client, gateway or conformance harness at a
fastgeoapi deployment and you want to know what you will meet before you
meet it. This page is the answer sheet: where discovery starts, what the
server declares, where the declaration and the behaviour part company,
and how each of the two surfaces expects to be authenticated.

Everything here is discoverable from a deployment itself. It is written
down so you do not have to discover it by failing. The public demo is the
worked example throughout, and every figure below was measured against
it rather than read off a specification.

## Two surfaces, one configuration

A deployment serves the same collections twice. **OGC API** over HTTP,
which any standards-aware client already speaks, and **MCP**, which
presents those collections as tools generated from the OpenAPI document
the server already publishes.

They do not share an authorization model, and that is the single fact
most likely to cost you an afternoon. The OGC surface is a resource
server in front of the operator's identity provider. The MCP surface is
its own OAuth 2.0 authorization server, proxying that same identity
provider. A token that opens one does not open the other.

## Start from discovery, not from this page

| Surface | What                                     | On the demo                                                             |
| ------- | ---------------------------------------- | ----------------------------------------------------------------------- |
| OGC API | Landing page                             | `https://fastgeoapi.fly.dev/geoapi`                                     |
| OGC API | Conformance declaration                  | `https://fastgeoapi.fly.dev/geoapi/conformance`                         |
| OGC API | OpenAPI document                         | `https://fastgeoapi.fly.dev/geoapi/openapi`                             |
| MCP     | Endpoint (Streamable HTTP)               | `https://fastgeoapi.fly.dev/mcp/`                                       |
| MCP     | Protected resource metadata (RFC 9728)   | `https://fastgeoapi.fly.dev/.well-known/oauth-protected-resource/mcp/`  |
| MCP     | Authorization server metadata (RFC 8414) | `https://fastgeoapi.fly.dev/.well-known/oauth-authorization-server/mcp` |
| MCP     | Server card ([SEP-2127][sep2127])        | `https://fastgeoapi.fly.dev/.well-known/mcp-server-card`                |

[sep2127]: https://github.com/modelcontextprotocol/modelcontextprotocol/pull/2127

**The metadata paths are path-aware.** The MCP server is mounted under
`/mcp`, so its metadata lives at
`/.well-known/oauth-authorization-server/mcp`; the bare
`/.well-known/oauth-authorization-server` is a `404`, because the root of
a deployment is an OGC API rather than an MCP server. A client that
assumes the bare path concludes there is no authorization server at all.

Only the three MCP discovery documents — the two metadata documents and
the card — answer without credentials. Everything else on either surface
answers `401` first, which is by design: the challenge is where discovery
starts. The card in particular is a cheap first probe, since it names the
transport and the protocol versions with no authentication at all, and on
the demo reports `streamable-http` with `2026-07-28` and `2025-11-25`.

## What the OGC API surface declares

Measured on the demo, 15 September 2026: **29 conformance classes**.

| Family              | Classes                                                                                                         |
| ------------------- | --------------------------------------------------------------------------------------------------------------- |
| OGC API - Common    | `core`, `landing-page`, `json`, `html`, `oas30`, `collections`, `schemas`, `advanced-property-roles`            |
| OGC API - Features  | `core`, `geojson`, `html`, `oas30`, `crs`, `queryables`, `queryables-query-parameters`, `create-replace-delete` |
| OGC API - Tiles     | `core`, `tileset`, `tilesets-list`, `geodata-tilesets`, `mvt`, `oas30`                                          |
| OGC API - Processes | `core`, `json`, `oas30`, `ogc-process-description`, `callback`                                                  |
| CQL2                | `basic-cql2`, `cql2-text`                                                                                       |

The list is not fixed: fastgeoapi derives part of it from the providers a
deployment actually configures, so read it from the deployment you are
testing rather than from this table.

## Where the declaration and the behaviour part company

Four divergences are worth knowing before you file a bug against your own
client. All four were measured on the demo; the first two are upstream
pygeoapi behaviour, not deployment configuration.

**Transactions are declared but not offered.**
`ogcapi-features-4/1.0/conf/create-replace-delete` appears in the
declaration of every pygeoapi deployment, including read-only ones,
because the class list is a static constant. A write to a read-only
collection answers `400 InvalidParameterValue` with
`"Collection is not editable"` — measured for both `POST /items` and
`PUT /items/{id}`. Treat the class as unverified until a write succeeds,
and note that the refusal is a `400` rather than the `405` a client
usually expects.

**CQL2 filtering works but is not declared.** The declaration carries
`cql2-text` and `basic-cql2` but neither
`ogcapi-features-3/1.0/conf/filter` nor `conf/features-filter`, which are
the classes Part 3 uses to say "the `filter` parameter exists on items".
The parameter nevertheless works: `filter=class IN ('primary')` with
`filter-lang=cql2-text` returned three features, all of class `primary`.
The practical consequence lands on clients that check first — QGIS, for
one, enables filter pushdown only when both classes are present, so a
subset set on the layer produces no request at all. If your client
negotiates on the declaration, expect to filter locally.

**Two places where the published OpenAPI does not describe the
response.** A harness that validates against the document will reject
correct answers:

- the tileset list of a collection responds `{links, tilesets}`, while
  the schema declared for it requires `tileMatrixSetLinks` — a member no
  response contains;
- `skipGeometry=true` produces `"geometry": null`, which RFC 7946 §3.2
  allows and the declared `featureGeoJSON` schema forbids, since its
  `geometry` is a `oneOf` over the seven geometry types with no null.

Both are upstream schema defects rather than server faults. If your
harness validates structured output — an MCP client does — it will
discard good responses; validate the data, not the document, until they
are fixed.

**A tile archive may not hold every zoom.** Tiles come from PMTiles
archives, and an archive is free to hold a narrow range: the demo's
Overture places archive holds zoom 14 only. Requests outside the range
answer `204`, not an error. The HTML tile viewer bundled with pygeoapi
does not pass `minzoom` to its map, so it asks for zooms that cannot
exist and shows an empty map without saying why; a collection whose
extent is pinned to a city hides the symptom, which is why the demo's is.

## Authenticating on the OGC surface

An unauthenticated request answers `401` with a challenge naming the
scheme and the realm:

```text
HTTP/2 401
www-authenticate: Bearer realm="https://fastgeoapi.fly.dev/geoapi/"
```

The realm is the audience the deployment expects, so it is also the
`resource` to ask your token for. The demo accepts the OAuth 2.0
**client credentials** grant against its identity provider; the client it
publishes for that purpose, and a full worked exchange, are in
[Getting started](../../operators/tutorials/getting-started.md). Tokens
are validated against the provider's JWKS with the expected issuer and
audience, which means a token minted for a different resource is refused
even though it is perfectly valid.

## Authenticating on the MCP surface

Follow the chain rather than hard-coding it. An unauthenticated
`initialize` answers:

```text
HTTP/2 401
www-authenticate: Bearer scope="openid",
  resource_metadata="https://fastgeoapi.fly.dev/.well-known/oauth-protected-resource/mcp/"
```

That document names the authorization server, whose metadata reports, on
the demo:

| Key                                     | Value                                            |
| --------------------------------------- | ------------------------------------------------ |
| `issuer`                                | `https://fastgeoapi.fly.dev/mcp/`                |
| `grant_types_supported`                 | `authorization_code`, `refresh_token`            |
| `response_types_supported`              | `code`                                           |
| `code_challenge_methods_supported`      | `S256`                                           |
| `token_endpoint_auth_methods_supported` | `none`, `private_key_jwt`                        |
| `scopes_supported`                      | `openid`, `profile`, `email`, `offline_access`   |
| `registration_endpoint`                 | present — Dynamic Client Registration (RFC 7591) |
| `client_id_metadata_document_supported` | `true` — CIMD                                    |
| `jwks_uri`                              | **absent**, deliberately                         |

Three consequences, in the order they tend to bite.

**There is no `client_credentials` here.** A client completes an
interactive authorization code flow with PKCE. A machine-to-machine
integration with no human in the loop is not possible over plain OAuth on
this surface — which is the opposite of the OGC surface, where client
credentials is exactly what the demo expects.

**You may register dynamically or present a CIMD.** Both are supported:
Dynamic Client Registration at the registration endpoint, or a Client ID
Metadata Document — a URL as your `client_id`, whose document publishes
your redirect URIs.

**The access token is a reference token, and nobody else can validate
it.** It is a JWT signed with `HS256` from a key derived from the
deployment's own upstream client secret. No `jwks_uri` is published, so
adding this authorization server to another resource server's list of
trusted issuers cannot work. There is no `sub` either: the subject lives
upstream, behind the `jti`. The token is meaningful to the server that
issued it and to nothing else.

For carrying identity across organisations without a browser, the
direction is enterprise-managed authorization, where your own OpenID
Provider issues an assertion that is exchanged at the token endpoint. The
grant exists **only** for issuers an operator has named; with none
configured the token endpoint answers `unsupported_grant_type` and the
metadata does not advertise it, which is how a deployment that has not
opted in looks from outside. The operator's side is under
[Enabling the MCP server](../../operators/how-to/enabling-mcp.md).

## What is verified, and what is not

The [supported specifications](mcp-specifications.md) matrix is the
honest inventory: each row says whether it is exercised against a live
deployment, covered by tests only, or still in progress. Read it before
planning a conformance run, so nothing comes as a surprise half-way
through.

If you want to reproduce the surface rather than trust it, the
configuration the demo serves is
[published and runnable](../../operators/how-to/index.md#the-demos-own-configuration-and-where-to-read-it):
the same document, in the repository and in the bucket the deployment
reads.
