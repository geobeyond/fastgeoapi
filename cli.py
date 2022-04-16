"""Command-line interface."""
import typer

app = typer.Typer()


@app.command()
def main() -> None:
    """fastgeoapi."""


if __name__ == "__main__":
    app(prog_name="fastgeoapi")  # pragma: no cover
