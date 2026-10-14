---
icon: material/laptop
---

# :material-laptop: Development setup

```bash
git clone https://github.com/geobeyond/fastgeoapi.git
cd fastgeoapi
uv sync --all-extras --dev
```

`uv` is the only prerequisite besides Python 3.12. The extras matter:
`--all-extras` brings in `geoparquet`, without which the DuckDB provider
and a good part of the suite are skipped rather than run.

Copy the environment the server reads:

```bash
cp .env.example .env
```

`HOST` and `PORT` are required — deliberately, so a half-configured
deployment fails at startup rather than serving from a default nobody
chose. The one exception is `fastgeoapi config edit`, which reads no
settings at all, because editing a pygeoapi document must work for
someone who does not run fastgeoapi.

Then:

```bash
uv run fastgeoapi run --reload
```

## The editor's page

The configuration editor ships a compiled page. A checkout does not have
one until you build it:

```bash
cd frontend && npm install && npm run build
```

Without it the API still works — that is what it is for — and the
command says so instead of serving a puzzling 404. The frontend has its
own toolchain and its own formatter; see
[running the tests](running-the-tests.md).

## The HTML pages

The [native HTML pages](../../operators/how-to/html-pages.md) live in two
places. The code that renders them is in `app/html`. Their files are in
the `fastgeoapi-html` package under `packages/fastgeoapi-html`: the Jinja
templates, the message catalogs, and the compiled assets. The package is
a member of the uv workspace, and the `html` extra installs it from
there:

```bash
uv sync --extra html
```

The assets are built from `frontend/pages`, the TypeScript of the maps,
forms and viewers and the stylesheet of the pages. `npm run build`, the
command that builds the editor, also writes them into
`packages/fastgeoapi-html/fastgeoapi_html/static`; `npm run build:pages`
builds the pages alone. Git ignores that directory, and the wheel carries
it.

Without the build the pages still render, as plain HTML with no style,
maps or forms, and the log says
`no compiled assets in …: the pages have no style nor islands`.

To see them, set `DEV_FASTGEOAPI_HTML_PAGES=native` and open any page
with `?f=html`.

## The documentation

```bash
uv sync --group docs
uv run zensical serve
```

The `docs` group is separate so the test environments do not carry it.
