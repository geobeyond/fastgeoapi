"""The translations of the pages, read from the catalogs of their package."""

from __future__ import annotations

import gettext
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po
from babel.support import Translations

DOMAIN = "messages"


@lru_cache(maxsize=32)
def translations(locale_dir: Path, language: str) -> gettext.NullTranslations:
    """The catalog of ``language``, or no translation when the package has none.

    The catalog is read from its ``.po`` source and compiled in memory, so
    the package ships no binary file and a checkout serves its catalogs as
    they are.
    """
    source = locale_dir / language / "LC_MESSAGES" / f"{DOMAIN}.po"
    if not source.is_file():
        return gettext.NullTranslations()
    with source.open("rb") as handle:
        catalog = read_po(handle, locale=language)
    compiled = BytesIO()
    write_mo(compiled, catalog)
    compiled.seek(0)
    return Translations(fp=compiled, domain=DOMAIN)
