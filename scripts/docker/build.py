"""Build the Dockerfile."""

import logging
import shlex
import shutil
import subprocess  # noqa: S404
from pathlib import Path
from typing import Optional

import typer

logger = logging.getLogger(__name__)


app = typer.Typer(pretty_exceptions_show_locals=False)


@app.command(name="build")
def main(
    base_image_name: str = typer.Option(  # noqa: B008
        default="registry.gitlab.com/geobeyond/georoma-fastgeoapi"
    ),
    build_context_path: str = typer.Option(  # noqa: B008
        default=str(Path(__file__).parent.parent.parent)  # noqa: B008
    ),
    default_git_branch: str = typer.Option(  # noqa: B008
        default=None,
        help="Name of the git branch to use as the base for the docker cache",
    ),
    docker_platform: str = typer.Option(  # noqa: B008
        default="linux/amd64",
        help="Docker architecture to use as the target platform for the build",
    ),
    use_cache: bool = typer.Option(  # noqa: B008
        default=True,
        help="Use Docker cache for the build",
    ),
):
    """Build the project's docker image."""
    logging.basicConfig(level=logging.INFO)
    git_command = shutil.which("git")
    docker_command = shutil.which("docker")
    if git_command is None:
        typer.echo("git command not found")
        raise typer.Abort()
    elif docker_command is None:
        typer.echo("docker command not found")
        raise typer.Abort()
    else:
        default_branch = (
            default_git_branch
            if default_git_branch is not None
            else _run_external_command(
                f"{git_command} rev-parse --abbrev-ref origin/HEAD"
            )
        )
        current_git_branch = _run_external_command(
            f"{git_command} rev-parse --abbrev-ref HEAD"
        )
        current_git_commit = _run_external_command(
            f"{git_command} rev-parse --short HEAD"
        )
        possible_docker_caches = []
        for possible_cache_base in (current_git_branch, default_branch):
            if possible_cache_base is not None:
                docker_tag_name = _sanitize_git_branch_name(possible_cache_base)  # noqa
                cache_image = f"{base_image_name}:{docker_tag_name}"
                # try to pull previous versions of the image,
                # in order to leverage docker build cache and speed up builds
                try:
                    _run_external_command(
                        f"{docker_command} pull {cache_image}",
                        capture_output=False,
                        raise_on_error=True,
                    )
                except subprocess.CalledProcessError:
                    logger.info("Could not run docker pull command")
                else:
                    possible_docker_caches.append(cache_image)
        build_command = (
            f"{docker_command} buildx build "
            f"--platform {docker_platform} "
            f"--tag '{base_image_name}:{_sanitize_git_branch_name(current_git_branch)}' "  # noqa B950
            f"--tag '{base_image_name}:{current_git_commit}' "
            f"--file {Path(__file__).parent.parent.parent / 'Dockerfile'} "
            f"--label git-commit={current_git_commit} "
            f"--label git-branch={current_git_branch}"
        )
        if use_cache:
            for cache_image in possible_docker_caches:
                build_command = " ".join(
                    (build_command, "--build-arg 'BUILDKIT_INLINE_CACHE=1'")
                )  # noqa
                build_command = " ".join(
                    (build_command, f"--cache-from {cache_image}")
                )  # noqa
        else:
            build_command = " ".join((build_command, f"--no-cache"))  # noqa
        build_command = " ".join((build_command, build_context_path))
        logger.info(f"build_command: {build_command}")
        _run_external_command(build_command, capture_output=False)


def _run_external_command(
    command: str,
    *,
    capture_output: Optional[bool] = True,
    raise_on_error: Optional[bool] = True,
) -> Optional[str]:
    """Run an external command using subprocess.

    Captures the external process' stdout and stderr too.
    """
    logger.info(f"command to run: {command!r}")
    kwargs = {"text": True}
    if capture_output:
        kwargs["capture_output"] = True
    process_result = subprocess.run(shlex.split(command), **kwargs)  # type: ignore[call-overload] # noqa
    if raise_on_error:
        process_result.check_returncode()
    result = process_result.stdout
    if capture_output:
        result = str(result.strip())
    return result


def _sanitize_git_branch_name(original: str) -> str:
    return original.replace("/", "-")


if __name__ == "__main__":
    app()
