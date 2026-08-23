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

**Known limit:** the MCP tool list is generated at startup and is NOT
refreshed by the webhook. Reloaded collections are served immediately
through the OGC API surface and by the existing MCP tools, but if the
set of collections changed and the MCP tool list matters, restart the
instance.
