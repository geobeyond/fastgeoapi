"""Nox sessions."""

import os
import shutil
from pathlib import Path
from textwrap import dedent

import nox

# Using standard nox with UV instead of nox-poetry
from nox import Session

session = nox.session


package = "app"
python_versions = ["3.12"]
nox.needs_version = ">= 2022.11.21"
nox.options.sessions = (
    "pre-commit",
    "safety",
    "bandit",
    "ty",
    "tests",
    "typeguard",
    "xdoctest",
    "docs-build",
)


def activate_virtualenv_in_precommit_hooks(session: Session) -> None:
    """Activate virtualenv in hooks installed by pre-commit.

    This function patches git hooks installed by pre-commit to activate the
    session's virtual environment. This allows pre-commit to locate hooks in
    that environment when invoked from git.

    Args:
        session: The NoxPoetrySession object.
    """
    assert session.bin is not None

    virtualenv = session.env.get("VIRTUAL_ENV")
    if virtualenv is None:
        return

    hookdir = Path(".git") / "hooks"
    if not hookdir.is_dir():
        return

    for hook in hookdir.iterdir():
        if hook.name.endswith(".sample") or not hook.is_file():
            continue

        text = hook.read_text()
        bindir = repr(session.bin)[1:-1]  # strip quotes
        if not ((Path("A") == Path("a") and bindir.lower() in text.lower()) or bindir in text):
            continue

        lines = text.splitlines()
        if not (lines[0].startswith("#!") and "python" in lines[0].lower()):
            continue

        header = dedent(
            f"""\
            import os
            os.environ["VIRTUAL_ENV"] = {virtualenv!r}
            os.environ["PATH"] = os.pathsep.join((
                {session.bin!r},
                os.environ.get("PATH", ""),
            ))
            """
        )

        lines.insert(1, header)
        hook.write_text("\n".join(lines))


@session(name="pre-commit", python="3.12")
def precommit(session: Session) -> None:
    """Lint using pre-commit."""
    args = session.posargs or ["run", "--all-files", "--show-diff-on-failure"]
    session.install(
        "ruff",
        "pre-commit",
        "pre-commit-hooks",
    )
    session.run("pre-commit", "clean")
    session.run("pre-commit", *args)
    if args and args[0] == "install":
        activate_virtualenv_in_precommit_hooks(session)


@session(python="3.12")
def safety(session: Session) -> None:
    """Scan dependencies for insecure packages.

    Requires SAFETY_API_KEY environment variable to be set.
    Get a free API key at https://safetycli.com
    """
    session.install(".")
    session.install("safety")
    # Build command with API key if available
    cmd = ["safety"]
    if "SAFETY_API_KEY" in os.environ:
        cmd.extend(["--key", os.environ["SAFETY_API_KEY"]])
    cmd.extend(["scan", "--detailed-output"])
    session.run(*cmd)


@session(python=python_versions)
def bandit(session: Session) -> None:
    """Scan code for vulnerabilities."""
    args = session.posargs or ["-r", "app", "-v"]
    session.install("bandit")
    session.run("bandit", *args)


@session(python=python_versions)
def ty(session: Session) -> None:
    """Type-check using ty (Astral's type checker)."""
    args = session.posargs or ["check", "app", "tests"]
    session.install(".")
    session.install(
        "ty",
        "pytest",
        "schemathesis>=4.0",
        "pytest-asyncio",
    )
    session.run("ty", *args)


@session(python=python_versions)
def tests(session: Session) -> None:
    """Run the test suite."""
    session.install(".")
    session.install(
        "coverage[toml]",
        "pytest",
        "pygments",
        "schemathesis>=4.0",
        "pytest-asyncio",
    )
    try:
        session.run("coverage", "run", "--parallel", "-m", "pytest", *session.posargs)
    finally:
        if session.interactive:
            session.notify("coverage", posargs=[])


@session
def coverage(session: Session) -> None:
    """Produce the coverage report."""
    args = session.posargs or ["report"]

    session.install("coverage[toml]")

    if not session.posargs and any(Path().glob(".coverage.*")):
        session.run("coverage", "combine")

    session.run("coverage", *args)


@session(python=python_versions)
def typeguard(session: Session) -> None:
    """Runtime type checking using Typeguard."""
    session.install(".")
    session.install(
        "pytest",
        "typeguard",
        "pygments",
        "schemathesis>=4.0",
        "pytest-asyncio",
    )
    session.run("pytest", f"--typeguard-packages={package}", *session.posargs)


@session(python=python_versions)
def xdoctest(session: Session) -> None:
    """Run examples with xdoctest."""
    if session.posargs:
        args = [package, *session.posargs]
    else:
        args = [f"--modname={package}", "--command=all"]
        if "FORCE_COLOR" in os.environ:
            args.append("--colored=1")

    session.install(".")
    session.install("xdoctest[colors]")
    session.run("python", "-m", "xdoctest", *args)


@session(name="docs-build", python="3.12")
def docs_build(session: Session) -> None:
    """Build the documentation."""
    args = session.posargs or ["--config-file", "mkdocs.yml"]
    # if not session.posargs and "FORCE_COLOR" in os.environ:
    #     args.insert(0, "--color")

    session.install(".")
    session.install(
        "mkdocs",
        "mkdocs-material",
        "mkdocs-material-extras",
        "mkdocs-material-extensions",
        "mkdocs-swagger-ui-tag",
        "mkdocs-typer",
        "mkdocstrings[python]",
        "termynal",
    )

    build_dir = Path("docs_build", "site")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    session.run("python", "-m", "mkdocs", "build", *args)


@session(python="3.12")
def docs(session: Session) -> None:
    """Build and serve the documentation with live reloading on file changes."""
    args = session.posargs
    session.install(".")
    session.install(
        "mkdocs",
        "mkdocs-material",
        "mkdocs-material-extras",
        "mkdocs-material-extensions",
        "mkdocs-swagger-ui-tag",
        "mkdocs-typer",
        "mkdocstrings[python]",
        "termynal",
    )

    build_dir = Path("docs_build", "site")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    session.run("python", "-m", "mkdocs", "serve", *args)
