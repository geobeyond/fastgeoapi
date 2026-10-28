---
icon: material/console
---

# :material-console: The command line

Installing fastgeoapi puts one command on your path. It has four
subcommands, and which one you run decides **what the process is allowed
to do** — that is the whole design, not an accident of packaging.

```bash
fastgeoapi --help
```

| Command                    | What it starts             | Can it change what is served?        |
| -------------------------- | -------------------------- | ------------------------------------ |
| `fastgeoapi run`           | the server                 | no — it only reads the configuration |
| `fastgeoapi openapi`       | nothing; writes a document | no                                   |
| `fastgeoapi config edit`   | the editor, on loopback    | it writes; it cannot activate        |
| `fastgeoapi config ingest` | nothing; writes resources  | it writes; it cannot activate        |

## `fastgeoapi run`

Serve the API.

```bash
fastgeoapi run
fastgeoapi run --host 127.0.0.1 --port 8000
fastgeoapi run --reload
fastgeoapi run --workers 4
```

| Option            | Default   | Meaning                                                                                                                                                                                                                                                                                                                           |
| ----------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--host`, `-h`    | `0.0.0.0` | address to bind                                                                                                                                                                                                                                                                                                                   |
| `--port`, `-p`    | `5000`    | port to bind                                                                                                                                                                                                                                                                                                                      |
| `--reload`, `-r`  | off       | restart on code changes; forces one worker                                                                                                                                                                                                                                                                                        |
| `--workers`, `-w` | `1`       | worker processes; with more than one, `run` turns on the configuration poll (`FASTGEOAPI_CONFIG_POLL_SECONDS=5` unless you set it) so that a reload reaches every worker within that interval; see [Hot reloading when there is more than one worker](../how-to/cloud-config.md#hot-reloading-when-there-is-more-than-one-worker) |

The configuration it reads comes from `PYGEOAPI_CONFIG` (or the
`DEV_`/`PROD_` variant for your `ENV_STATE`), and it may be a local path
or a bucket URL — see [Config from cloud storage](../how-to/cloud-config.md).

## `fastgeoapi openapi`

Write the OpenAPI document, with fastgeoapi's security schemes folded
into what pygeoapi generates.

```bash
fastgeoapi openapi
```

Useful in CI, where the document can be linted or diffed before a change
reaches a deployment. It reads the same configuration `run` would.

## `fastgeoapi config edit`

Open the configuration editor. Covered in full in
[Editing the configuration](../how-to/configuration-editor.md); the short version:

```bash
fastgeoapi config edit
fastgeoapi config edit --source s3://my-bucket/pygeoapi-config.yml
fastgeoapi config edit --port 9000
```

| Option           | Default                  | Meaning                              |
| ---------------- | ------------------------ | ------------------------------------ |
| `--source`, `-s` | your configured document | what to edit; a path or a bucket URL |
| `--port`, `-p`   | `8765`                   | port for the editor                  |
| `--augmented`    | off                      | also report what fastgeoapi adds     |

### It works with only pygeoapi installed

Installing fastgeoapi to edit a pygeoapi document is a reasonable thing
to want: the dry run builds the whole API and reads every data source,
which nothing upstream offers. So `config edit` asks for **no fastgeoapi
configuration at all** — no `HOST`, no `PORT`, no `.env`, no
authentication chain. Point it at a document and it opens.

`--augmented` is the opt-in for the other side of that line. It adds
what only fastgeoapi can say about a configuration: which OGC API
specifications it would mount, since the route table is built from the
resources rather than serving everything, and which MCP tools an agent
would see, derived from the OpenAPI the dry run has already built.

Asking for it where it cannot be answered is not an error — the answer
carries a line saying which half is missing and why, rather than failing
and handing back the barrier this command exists without.

It prints a per-run token and the address to open. There is **no
`--host`**: the editor refuses to serve anywhere but loopback, and that
refusal is a startup failure rather than a warning, because it is what
stands in for the authentication chain it deliberately does not have.

## `fastgeoapi config ingest`

Write pygeoapi resources for the GeoParquet and PMTiles collections of a
Portolan catalog, printed or merged into a configuration. It needs the
`portolan` extra, and is covered in full in
[Ingesting a Portolan catalog](../how-to/portolan-ingest.md).

```bash
fastgeoapi config ingest --from-portolan https://example.org/catalog/
fastgeoapi config ingest --from-portolan ./catalog --into pygeoapi-config.yml --prune
fastgeoapi config ingest --from-portolan s3://my-bucket/catalog/ --store-option region=eu-west-1 --json
```

| Option                 | Default    | Meaning                                                                                                                 |
| ---------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------- |
| `--from-portolan`      | required   | the catalog: its `catalog.json` or the folder that holds it, as a path or a URL                                         |
| `--into`               | none       | the configuration to merge the resources into, a path or a bucket URL; without it, they are printed                     |
| `--collection`         | all        | ingest this collection only; repeat for more                                                                            |
| `--prefix`             | none       | put this before every resource id                                                                                       |
| `--store-option`       | none       | a storage option for the buckets, as `key=value`; repeat for more                                                       |
| `--id-field`           | guessed    | the id column of a collection, as `collection=column`, when the catalog names none                                      |
| `--geometry-column`    | guessed    | the geometry column of a collection, as `collection=column`, when the catalog names none                                |
| `--check-ids`          | off        | count, in each GeoParquet collection, the rows that repeat an id or have none, reading the id column only; needs duckdb |
| `--prune`              | off        | with `--into`, remove this catalog's resources whose collection is gone from it                                         |
| `--strict`             | off        | exit with 1, before writing, when a collection is skipped or `--check-ids` finds a problem                              |
| `--json`               | off        | print the summary as JSON                                                                                               |
| `--max-documents`      | `10000`    | the most documents one walk reads, and the most items read for one collection                                           |
| `--max-document-bytes` | `33554432` | the largest document read, in bytes (32 MiB)                                                                            |

Without `--into` the resources go to stdout and the summary to stderr; with
it, the summary goes to stdout. It exits with 0 even when some collections
were skipped, with 1 on an error, when nothing is written, and with 2 on a
wrong command line.

`portolan fastgeoapi ingest` is the same command loaded by portolan-cli, with
the same options.

## Two roles, one program

`run` and `config edit` are the same project started differently, and
neither can do the other's job. The serving role carries no editor; the
authoring role carries no reload webhook, so it can write a
configuration but never put one into service.

`config ingest` is on the authoring side too: it writes a configuration
and never puts it into service.

The separation is tied to the **command** rather than to a setting on
purpose. A variable can be set by mistake in production — it has
happened here, `PROD_` where `DEV_` was read, and it cost a deployment —
while a container's `CMD` does not reach a different subcommand unless
somebody rewrites it.
