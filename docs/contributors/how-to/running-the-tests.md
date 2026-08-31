# Running the tests

```bash
uv run pytest
```

That is the whole suite. What CI runs is a set of nox sessions, each in
its own environment, and any of them can be reproduced:

```bash
uv run nox -s tests        # the suite, on a clean install
uv run nox -s typeguard    # the suite with runtime type checking
uv run nox -s xdoctest     # the examples in docstrings
uv run nox -s models-check  # the generated config models are current
uv run nox -s docs-build   # the site, in strict mode
```

## The frontend

The editor's page has its own suite, and it runs in CI as the `page`
job:

```bash
cd frontend
npm test          # vitest
npm run typecheck
npm run format:check
```

It is not optional dressing. The bridge between the form and the YAML
document is where a bug would be silent — a save that quietly drops
what the schema does not describe — so those tests are the ones holding
the design up.

## Before you push

```bash
uv run pre-commit run --all-files
```

!!! warning "It does not see untracked files"

    `--all-files` means every file **git knows about**. A file you have
    just created is not one of them, so the hooks skip it and CI is the
    first thing to complain. `git add -N` the new files first — this has
    cost red builds here more than once.

## Two traps this suite has sprung repeatedly

**Purged modules.** Some tests clear `sys.modules`. After that, a module
imported at the top of a test file and the same module imported inside a
test are two different objects — so a `monkeypatch` lands on the one
nobody calls, and the test passes alone while failing in the suite. Take
the module and the thing you are patching together, inside the test.

**Tests that never failed.** A green test proves nothing until you have
seen it red for the right reason. Where that is impossible — coverage
added to code that already works — break the code deliberately and check
that the test notices.
