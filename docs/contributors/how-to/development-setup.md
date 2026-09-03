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

## The documentation

```bash
uv sync --group docs
uv run zensical serve
```

The `docs` group is separate so the test environments do not carry it.
