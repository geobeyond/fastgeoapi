---
icon: material/puzzle-outline
---

# :material-puzzle-outline: How it is put together

fastgeoapi is not a fork of pygeoapi and not a wrapper around its CLI.
It builds pygeoapi in process, from a configuration it may have read
from anywhere, and mounts the result inside a FastAPI application it
also owns. Three consequences follow, and most of the codebase is one of
them.

## pygeoapi is constructed, not launched

Upstream builds its API from a file path in an environment variable, at
import time. fastgeoapi instead calls the pieces directly — build the
OpenAPI document, build the `API` object, derive the route table — which
is what makes everything else on this page possible.

The cost is a seam: the route table has to agree with what pygeoapi
would have served on its own. That agreement is not assumed but
asserted, by a test that compares the routes we mount against the ones
upstream produces.

## Data and configuration are read through one layer

Anything that can live in object storage — the configuration document,
the OpenAPI artefact, a GeoParquet dataset — is reached through a single
`Protocol` with one backend behind it. A local directory and a bucket
are the same shape, so a code path that works on one works on the other,
and the tests that matter run against a real S3 rather than a mock.

That layer is also where a hard-won lesson lives: the library underneath
reads the standard cloud environment variables in _every_ constructor,
with no way to opt out, so a dataset that names its own endpoint can
still be sent somewhere else entirely. Where that matters, the
environment is displaced for the length of the call.

## Providers keep pygeoapi's contract and gain a second face

pygeoapi calls providers synchronously, from a threadpool that on a
small machine holds five threads. fastgeoapi leaves that contract alone
and lets a provider add an awaitable twin for each method it can serve
without blocking; the tile data route awaits such providers on the event
loop and sends every other one down the threadpool path unchanged. The
reasoning is in [Two faces for a provider](async-providers.md), the
recipe in [Writing an async provider](../how-to/writing-an-async-provider.md).

## Writing a configuration and activating it are separate powers

A configuration can be applied without restarting, through a webhook on
the running deployment. That makes editing it a different kind of act
than editing a file — and it is why the
[editor](../../operators/how-to/configuration-editor.md) runs as its own
command, mounts no webhook, and refuses to serve anywhere but loopback.

One surface that could both write a configuration and put it into
service would mean whoever reaches it decides what the server serves.
Keeping them apart costs an extra gesture and removes that.
