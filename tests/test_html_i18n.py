"""The catalogs of the pages, read from their source.

``app.*`` is imported at the top of this module.
"""

import gettext

from app.html.i18n import translations

CATALOG = (
    'msgid ""\nmsgstr ""\n"Content-Type: text/plain; charset=UTF-8\\n"\n\n'
    'msgid "Collections"\nmsgstr "Collezioni"\n'
)


def _locale(root):
    directory = root / "it" / "LC_MESSAGES"
    directory.mkdir(parents=True)
    (directory / "messages.po").write_text(CATALOG)
    return root


def test_a_language_with_a_catalog_is_translated(tmp_path):
    assert translations(_locale(tmp_path), "it").gettext("Collections") == "Collezioni"


def test_a_language_without_a_catalog_keeps_the_english_text(tmp_path):
    catalog = translations(_locale(tmp_path), "fr")

    assert type(catalog) is gettext.NullTranslations
    assert catalog.gettext("Collections") == "Collections"


def test_a_catalog_is_read_once(tmp_path):
    locale = _locale(tmp_path)

    assert translations(locale, "it") is translations(locale, "it")
