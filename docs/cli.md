# The command line

Installing fastgeoapi puts one command on your path. It has three
subcommands, and which one you run decides **what the process is allowed
to do** — that is the whole design, not an accident of packaging.

```bash
fastgeoapi --help
```

| Command                  | What it starts             | Can it change what is served?        |
| ------------------------ | -------------------------- | ------------------------------------ |
| `fastgeoapi run`         | the server                 | no — it only reads the configuration |
| `fastgeoapi openapi`     | nothing; writes a document | no                                   |
| `fastgeoapi config edit` | the editor, on loopback    | it writes; it cannot activate        |

## `fastgeoapi run`

Serve the API.

```bash
fastgeoapi run
fastgeoapi run --host 127.0.0.1 --port 8000
fastgeoapi run --reload
```

| Option            | Default   | Meaning                                    |
| ----------------- | --------- | ------------------------------------------ |
| `--host`, `-h`    | `0.0.0.0` | address to bind                            |
| `--port`, `-p`    | `5000`    | port to bind                               |
| `--reload`, `-r`  | off       | restart on code changes; forces one worker |
| `--workers`, `-w` | `1`       | worker processes                           |

The configuration it reads comes from `PYGEOAPI_CONFIG` (or the
`DEV_`/`PROD_` variant for your `ENV_STATE`), and it may be a local path
or a bucket URL — see [Config from cloud storage](cloud-config.md).

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
[Editing the configuration](configuration-editor.md); the short version:

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

## Two roles, one program

`run` and `config edit` are the same project started differently, and
neither can do the other's job. The serving role carries no editor; the
authoring role carries no reload webhook, so it can write a
configuration but never put one into service.

The separation is tied to the **command** rather than to a setting on
purpose. A variable can be set by mistake in production — it has
happened here, `PROD_` where `DEV_` was read, and it cost a deployment —
while a container's `CMD` does not reach a different subcommand unless
somebody rewrites it.
