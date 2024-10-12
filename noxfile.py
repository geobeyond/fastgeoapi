"""Nox sessions."""

import os
import shutil
import sys
from pathlib import Path
from textwrap import dedent

import nox

try:
    from nox_poetry import Session as NoxPoetrySession
    from nox_poetry import session as nox_session
except ImportError:
    message = f"""\
    Nox failed to import the 'nox-poetry' package.

    Please install it using the following command:

    {sys.executable} -m pip install nox-poetry"""
    raise SystemExit(dedent(message)) from None


package = "app"
python_versions = ["3.10"]
nox.needs_version = ">= 2022.11.21"
nox.options.sessions = (
    "pre-commit",
    "safety",
    "bandit",
    "mypy",
    "tests",
    "typeguard",
    "xdoctest",
    "docs-build",
)


def activate_virtualenv_in_precommit_hooks(session: NoxPoetrySession) -> None:
    """Activate virtualenv in hooks installed by pre-commit.

    This function patches git hooks installed by pre-commit to activate the
    session's virtual environment. This allows pre-commit to locate hooks in
    that environment when invoked from git.

    Args:
        session: The NoxPoetrySession object.
    """
    assert session.bin is not None  # noqa: S101

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
        if not (
            Path("A") == Path("a") and bindir.lower() in text.lower() or bindir in text
        ):
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


@nox_session(name="pre-commit", python="3.10")
def precommit(session: NoxPoetrySession) -> None:
    """Lint using pre-commit."""
    args = session.posargs or ["run", "--all-files", "--show-diff-on-failure"]
    session.install(
        "black",
        "darglint",
        "flake8",
        "flake8-bandit",
        "flake8-bugbear",
        "flake8-docstrings",
        "flake8-rst-docstrings",
        "pep8-naming",
        "pre-commit",
        "pre-commit-hooks",
        "pyupgrade",
        "isort",
    )
    session.run("pre-commit", "clean")
    session.run("pre-commit", *args)
    if args and args[0] == "install":
        activate_virtualenv_in_precommit_hooks(session)


@nox_session(python="3.10")
def safety(session: NoxPoetrySession) -> None:
    """Scan dependencies for insecure packages."""
    requirements = session.poetry.export_requirements()
    session.install("safety")
    session.run(
        "safety",
        "check",
        "-i",
        "51457",
        "-i",
        "51358",
        # 51668: https://github.com/sqlalchemy/sqlalchemy/pull/8563,
        # still in beta + major version change sqlalchemy 2.0.0b1
        "-i",
        "51668",
        "-i",
        "61493",
        "-i",
        "70612",
        "--full-report",
        f"--file={requirements}",
    )


@nox_session(python=python_versions)
def bandit(session: NoxPoetrySession) -> None:
    """Scan code for vulnerabilities."""
    args = session.posargs or ["-r", "app", "-v"]
    session.install("bandit")
    session.run("bandit", *args)


@nox_session(python=python_versions)
def mypy(session: NoxPoetrySession) -> None:
    """Type-check using mypy."""
    args = session.posargs or ["app", "tests", "--namespace-packages"]
    session.install(".")
    session.install("mypy", "pytest")
    session.run("mypy", *args)
    if not session.posargs:
        session.run("mypy", f"--python-executable={sys.executable}", "noxfile.py")


@nox_session(python=python_versions)
def tests(session: NoxPoetrySession) -> None:
    """Run the test suite."""
    session.install(".")
    session.install("coverage[toml]", "pytest", "pygments", "schemathesis")
    try:
        # session.run("coverage", "run", "--parallel", "-m", "pytest", *session.posargs)
        session.run("py.test", *session.posargs)
    finally:
        if session.interactive:
            session.notify("coverage", posargs=[])


@nox_session
def coverage(session: NoxPoetrySession) -> None:
    """Produce the coverage report."""
    args = session.posargs or ["report"]

    session.install("coverage[toml]")

    if not session.posargs and any(Path().glob(".coverage.*")):
        session.run("coverage", "combine")

    session.run("coverage", *args)


@nox_session(python=python_versions)
def typeguard(session: NoxPoetrySession) -> None:
    """Runtime type checking using Typeguard."""
    session.install(".")
    session.install("pytest", "typeguard", "pygments", "schemathesis")
    session.run("pytest", f"--typeguard-packages={package}", *session.posargs)


@nox_session(python=python_versions)
def xdoctest(session: NoxPoetrySession) -> None:
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


@nox_session(name="docs-build", python="3.10")
def docs_build(session: NoxPoetrySession) -> None:
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
        "termynal",
    )

    build_dir = Path("docs_build", "site")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    session.run("python", "-m", "mkdocs", "build", *args)


@nox_session(python="3.10")
def docs(session: NoxPoetrySession) -> None:
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
        "termynal",
    )

    build_dir = Path("docs_build", "site")
    if build_dir.exists():
        shutil.rmtree(build_dir)

    session.run("python", "-m", "mkdocs", "serve", *args)
