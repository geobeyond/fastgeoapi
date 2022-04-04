"""Command-line interface."""
import click


@click.command()
@click.version_option()
def main() -> None:
    """fastgeoapi."""


if __name__ == "__main__":
    main(prog_name="fastgeoapi")  # pragma: no cover
