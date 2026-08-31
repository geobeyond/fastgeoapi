# Contributing

You are working on fastgeoapi itself — fixing something, adding a
provider, or trying to understand why a piece is shaped the way it is.

<div class="grid cards" markdown>

- :material-wrench: **[How-to guides](how-to/development-setup.md)**

  Getting a working checkout, and running the suite the way CI runs
  it.

- :material-book-open-variant: **[API reference](reference/index.md)**

  Generated from the docstrings, which is where the reasoning lives.

- :material-lightbulb: **[Explanation](explanation/architecture.md)**

  How the pieces fit: the two roles, the programmatic construction of
  pygeoapi, the storage layer everything reads through.

</div>

## Before anything else

Contributions go through
[CONTRIBUTING.md](https://github.com/geobeyond/fastgeoapi/blob/main/CONTRIBUTING.md).
Two conventions matter more than the rest, because the whole codebase
assumes them.

**Docstrings carry the reasoning, not the mechanics.** A docstring that
restates the signature is noise; one that says why a thing is done this
way and what breaks otherwise is the only record of a decision that
would otherwise have to be rediscovered.

**A test fails before it passes.** Not as ceremony: a test written
against working code and never seen red can assert nothing at all, and
this project has caught that happening more than once.
