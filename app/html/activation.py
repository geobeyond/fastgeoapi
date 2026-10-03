"""Which HTML pages the sub-app serves, from fastgeoapi's settings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.html.package import html_package
from app.html.pages import NativePages
from app.html.registry import PAGES

NATIVE = "native"


def native_pages(*, templates: Path | None = None, static: Path | None = None) -> NativePages:
    """Fastgeoapi's pages; templates in ``templates`` replace the package's of the same name.

    ``static`` replaces the package's compiled assets, for a build made
    elsewhere. Raises :class:`HtmlPagesUnavailableError` without the package.
    """
    package = html_package()
    search = [templates, package.templates] if templates is not None else [package.templates]
    return NativePages(
        PAGES, search, package.locale, static if static is not None else package.static
    )


def pages_from(settings: Any) -> NativePages | None:
    """The native pages when the settings ask for them; None keeps pygeoapi's."""
    if settings.FASTGEOAPI_HTML_PAGES != NATIVE:
        return None
    override = settings.FASTGEOAPI_HTML_TEMPLATES
    return native_pages(templates=Path(override) if override else None)


def default_pages() -> NativePages | None:
    """The pages of fastgeoapi's settings; pygeoapi's without settings."""
    # Imported here: building the settings needs a configured fastgeoapi, and
    # the sub-app is also built by tools that only have pygeoapi.
    try:
        from app.config.app import configuration
    except (ImportError, ValueError):
        return None
    return pages_from(configuration)
