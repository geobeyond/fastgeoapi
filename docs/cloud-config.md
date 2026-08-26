# Config from cloud object storage

`PYGEOAPI_CONFIG` (per-environment: `DEV_PYGEOAPI_CONFIG` /
`PROD_PYGEOAPI_CONFIG`) accepts a local path or an object-storage URL —
one code path for both, built on [obstore](https://developmentseed.org/obstore/):

| Source                        | Example                                           |
| ----------------------------- | ------------------------------------------------- |
| Local file                    | `pygeoapi-config.yml`                             |
| Amazon S3                     | `s3://my-bucket/tenants/acme/pygeoapi-config.yml` |
| S3-compatible (Tigris, MinIO) | same as S3 + `AWS_ENDPOINT_URL_S3`                |
| Google Cloud Storage          | `gs://my-bucket/pygeoapi-config.yml`              |
| Azure Blob Storage            | `az://container/pygeoapi-config.yml`              |

Credentials come exclusively from each provider's standard environment
variables (`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` /
`AWS_ENDPOINT_URL_S3`, `GOOGLE_APPLICATION_CREDENTIALS`,
`AZURE_STORAGE_ACCOUNT_NAME` / `AZURE_STORAGE_ACCOUNT_KEY`). fastgeoapi
never defines its own credential settings.

The configuration is read as bytes and handed to pygeoapi as an
in-memory dictionary: no temporary file is written, and `${VAR}`
placeholders inside the config are resolved with the same semantics as
vanilla pygeoapi.

## The OpenAPI artifact

`PYGEOAPI_OPENAPI` is an **output** target and accepts the same set of
sources — local path or bucket URL. The runtime never reads it back
(everything is built in memory); it exists for external consumers such
as the control plane or CLI tooling.

- Startup writes it only when it is missing.
- An applied reload always rewrites it, so the artifact never goes
  stale against the config that is serving.
- A failed write is logged as a warning and never aborts startup or a
  reload.
- Writing to a bucket needs read-write credentials; reading the config
  alone works with read-only ones.

`fastgeoapi openapi` writes the security-enriched JSON document to the
same target (with a `.json` suffix), through the same layer.

## Hot reload

After updating the config object, call the reload webhook:

```bash
curl -X POST https://example.org/admin/config/reload
```

- Responds `202 Accepted` immediately; the reload happens in the
  background.
- Idempotent via the object's ETag: same ETag → outcome `unchanged`,
  no rebuild.
- A broken config never replaces the running one: the outcome is
  `failed` and the previous config keeps serving.
- The mounted OGC API surface follows the config: only the
  specifications the configured resources actually expose are served
  (a deployment without EDR resources answers 404 on the EDR paths),
  and the set is recomputed on every applied reload.
- `GET /admin/config/reload` returns the last outcome:

```json
{
  "status": "idle",
  "last": {
    "outcome": "applied",
    "at": "2026-08-22T17:00:00+00:00",
    "etag": "\"abc-123\""
  }
}
```

The endpoint is protected by the same authentication chain configured
for the API (API key, JWT via JWKS, or OPA) — no separate secret to
manage.

**If the reload answers `unchanged` right after you changed the file,
the store is still serving the old one.** Idempotence compares the
ETag the store reports with the one currently loaded, so a stale read
is honestly reported as "nothing to do". Observed twice on Tigris after
overwriting the same key, converging on its own — once within seconds
of a second `POST`, once after several minutes. Trigger it again, or
avoid the situation entirely: **write a new key and point
`PYGEOAPI_CONFIG` at it** rather than overwriting, which also gives you
a configuration history and a rollback.

The MCP tool list follows the reload as well. It is generated from the
OpenAPI document, so a collection added to the configuration becomes an
MCP tool — and one removed stops being offered — without restarting the
instance.

**What a connected client sees:** the server is correct straight away,
but nothing pushes the change out. This FastMCP version has no
server-side `notifications/tools/list_changed`, and the stateless
transport cannot send server-initiated messages by design, so a client
keeps the list it cached until it asks for it again — normally when it
reconnects.
