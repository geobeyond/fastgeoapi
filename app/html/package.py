"""Where the files of the HTML pages are: the fastgeoapi-html package."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

PACKAGE = "fastgeoapi_html"

MISSING = (
    "native HTML pages need the fastgeoapi-html package: install fastgeoapi[html], "
    "or set DEV_FASTGEOAPI_HTML_PAGES (PROD_FASTGEOAPI_HTML_PAGES in production) to pygeoapi"
)


class HtmlPagesUnavailableError(RuntimeError):
    """The native pages are asked for, and their package is not installed."""


@dataclass(frozen=True)
class HtmlPackage:
    """The directories of the package."""

    templates: Path
    static: Path
    locale: Path


def html_package() -> HtmlPackage:
    """The directories of the installed package; :class:`HtmlPagesUnavailableError` without it."""
    try:
        module = import_module(PACKAGE)
    except ModuleNotFoundError as error:
        raise HtmlPagesUnavailableError(MISSING) from error
    return HtmlPackage(Path(module.TEMPLATES), Path(module.STATIC), Path(module.LOCALE))
