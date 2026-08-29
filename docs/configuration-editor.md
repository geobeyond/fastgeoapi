# Editing the configuration

The configuration decides what the server serves: which collections
exist, which specifications get mounted, how providers reach their data.
Since it can live in a bucket and be applied without a restart, editing
it is no longer "change a file, restart, see what happens" — which is
what this surface is for.

```bash
fastgeoapi config edit
```

It prints where it is listening and a secret for the session:

```
Editing s3://my-bucket/pygeoapi-config.yml
Editor listening on http://127.0.0.1:8765
Token: A7ks…

  Open http://127.0.0.1:8765 and paste the token when it asks.

  curl -H 'X-Fastgeoapi-Editor-Token: A7ks…' http://127.0.0.1:8765/editor/config
```

Open that address and the page asks for the token once. **The address
never carries it**: a secret in a URL survives in browser history, rides
along in the `Referer` sent to anything the page loads, and stays in the
shell history that printed it. What the page gets back instead is an
`HttpOnly` cookie — which also _confines_, since a browser binds a
cookie to the origin that set it and will not send it to your
deployment, even by mistake.

If the command says the page is not compiled, the API still works —
that is what it is for. `cd frontend && npm install && npm run build`
adds the page; a release from PyPI has it already.

## The page

A form built from the schema of the pygeoapi you are actually running,
served by the editor rather than compiled in, so it cannot drift from
the version in front of you.

Three things about it are worth knowing, because each one is a mistake
it deliberately does not make.

**It does not own your document.** A form takes JSON and gives JSON
back, and that round trip loses whatever the schema does not describe —
which here means `store_options`, `engine_options`, every
provider-specific key, and all your comments. So the document stays the
truth and the form is a view: only the values you actually changed are
written back. Open it and save it without touching anything and the file
is returned **byte for byte** as it was.

**It shows your `${VAR}` placeholders.** Left to itself the form would
render `port: ${PORT}` as an empty number box and call your
configuration broken — and one keystroke would replace a value you
parameterised on purpose with nothing. Every scalar field therefore
accepts text as well, so a placeholder stays visible and stays put.

**It is not the authority on whether your document is valid.** The page
asks the server, which answers twice — as written, and as it would run.
That distinction cannot be made in a browser, which knows neither your
environment nor the deployment's.

## What it will not do

**It cannot put anything into service.** The editor mounts no reload
webhook — saving writes the document, nothing more. Activating it is a
separate gesture, against the deployment, with that deployment's own
credentials.

That separation is deliberate twice over. Writing a configuration and
activating it are different powers, and one surface holding both would
mean whoever reaches it decides what the server serves. And a dry run
empties the process caches: an editor sitting beside a live server would
degrade what that server is serving on every preview, taking request
latency back up with nobody able to connect cause to effect.

**It stays on loopback.** There is no OIDC chain in front of it —
demanding an OAuth flow to edit a file on your own machine would be
ceremony without security — so not being reachable from elsewhere is
what stands in its place. Asking it to serve on any other address is a
startup failure, not a warning.

## The endpoints

| Method | Path               | Answers                                            |
| ------ | ------------------ | -------------------------------------------------- |
| `GET`  | `/editor/config`   | the document as written, placeholders intact       |
| `POST` | `/editor/validate` | is it well formed — as source, and as it would run |
| `POST` | `/editor/dry-run`  | does it actually build                             |
| `PUT`  | `/editor/config`   | save it, if it validates                           |

They answer JSON and need no browser: use them from `curl`, from a
script, or as a check in CI on a configuration before it is merged. The
page is one caller among those, not the only way in.

### Two ways to be well formed

The document you edit is not the document that runs. Yours carries
`${VAR}` placeholders; the running one has them resolved. `port: ${PORT}`
is a string where the schema wants an integer — correct in the source,
wrong in the effective form.

So `validate` answers twice, and the effective answer carries the
variables it substituted. Without them the answer would not be
reproducible: the values come from wherever the editor is running.

### Saving refuses before it writes, never after

`PUT` validates and only then writes. A refusal that followed a write
would leave the store holding a configuration that cannot start, one
webhook call away from taking the service down.

It also says what it checked:

```json
{
  "saved": true,
  "activated": false,
  "checked": ["source", "effective"],
  "not_checked": ["dry-run: ask /editor/dry-run before relying on this"]
}
```

A dry run is not run on every save on purpose: against a remote dataset
it costs seconds, and an editor that made you wait would teach you to
route around it. So _saved_ does not mean _verified_, and the answer
says so rather than letting you assume it.

## What a dry run does — and what it does not

It builds the whole API from the candidate configuration, in isolation,
and then goes further than building, because building is not enough:

- a **provider is constructed without touching its data**, so a source
  that is not there mounts perfectly and fails on first read;
- asking for an item does not settle it either — pygeoapi's GeoJSON
  provider answers `200` with an empty collection when its file is
  missing, which is indistinguishable from a collection that is
  legitimately empty;
- so **the data source is checked directly**, through the same storage
  layer for a local path and a bucket alike.

!!! warning "It answers whether this builds _here_, never whether it works _there_"

    The build uses **your** environment and **your** credentials, not the
    deployment's. A bucket you can reach may be unreachable from the
    server; a variable set on your machine may be missing there.

    Every outcome carries the variables it resolved, so you can tell the
    two apart. Reading a green as a guarantee about production is the one
    way this feature can do harm instead of good.

What it does catch is most of what actually goes wrong: a mistyped key,
a provider that will not import, a missing extra, a path or an object
that is not where the configuration says it is.
