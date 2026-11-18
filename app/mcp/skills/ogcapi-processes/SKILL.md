---
name: ogcapi-processes
description: Run a process with OGC API - Processes and get its results. Use it to read what a process needs, execute it synchronously or as a job, and follow the job to its results.
---

# Running processes

A process takes inputs, does some work on the server and returns
outputs. Running one can write data, call other services or take time,
so **ask the user to confirm before you execute a process**, and show
them the inputs you are going to send.

## Read the description first

`GET /processes` lists the processes. `GET /processes/{processId}`
describes one:

- `inputs`: each input with its schema, and whether it is required
  (`minOccurs`).
- `outputs`: what the process returns.
- `jobControlOptions`: `sync-execute`, `async-execute`, or both.

Build the request from the schemas, not from the input names alone.

## Execute

`POST /processes/{processId}/execution` with a JSON body. The inputs go
in an object named `inputs`:

```json
{ "inputs": { "name": "World" } }
```

Inputs at the top level of the body, outside `inputs`, do not reach the
process.

- **Synchronously.** Without a preference, a process that supports it
  answers with its results, usually `200`.
- **As a job.** Send the header `Prefer` with the value `respond-async`.
  The server answers `201` with a `Location` header pointing to the job,
  `/jobs/{jobId}`.

## Follow a job

`GET /jobs/{jobId}` answers the job's `status`: `accepted`, `running`,
`successful`, `failed` or `dismissed`. Ask again until it is one of the
last three; wait a little between requests. When it is `successful`,
`GET /jobs/{jobId}/results` answers the outputs. When it is `failed`,
the job's `message` says why.

## When something looks wrong

- **A 400 answer on execute.** A required input is missing or a value
  does not match its schema. Inputs outside the `inputs` object count as
  missing.
- **A job that stays `accepted`.** The server has not started it yet.
  Keep asking at a slower pace rather than executing again; a second
  execute starts a second job.
- **Results that refer to a place you did not mean.** Coordinates in
  inputs are usually longitude first, then latitude. Check the input's
  schema.
