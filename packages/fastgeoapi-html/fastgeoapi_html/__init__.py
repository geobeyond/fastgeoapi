"""The files of fastgeoapi's HTML pages: templates, catalogs and compiled assets.

The package holds data only; fastgeoapi finds the files through these paths.
"""

from pathlib import Path

_HERE = Path(__file__).parent

TEMPLATES = _HERE / "templates"
"""The Jinja templates of the pages."""

STATIC = _HERE / "static"
"""The assets Vite compiles from ``frontend/pages``, with their manifest."""

LOCALE = _HERE / "locale"
"""The message catalogs, one directory per language."""
