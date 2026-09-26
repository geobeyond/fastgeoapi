---
title: OpenAPI reference (build-time)
icon: material/api
render_macros: true
---

# :material-api: OpenAPI reference (build-time)

The demo's OpenAPI document rendered at build time: dereferenced with
fastgeoapi's own resolver (`scripts/build_openapi_reference.py`) and
rendered by `essentials-openapi` through a Zensical macro (`main.py`).
The aim is a reference that belongs to the site — searchable, in the
theme, without a client-side script — next to the [live Swagger UI
page](openapi.md), which shows what the running instance serves.

Work in progress and not in the navigation yet: the rendered page is
heavy and the resolver leaves the CQL2 schema's `#/$defs` pointers
dangling. Both are tracked in the integration issue.

{{ generate_openapi("docs_build/openapi-resolved.json") }}
