"""Every string of the pages has its Italian translation.

No ``app.*`` import in this module: it reads the sources of ``app/html``.
"""

from importlib import import_module
from pathlib import Path

from babel.messages.extract import extract_from_dir
from babel.messages.pofile import read_po

JINJA = "jinja2.ext:babel_extract"


def _strings():
    html = import_module("fastgeoapi_html")
    templates = extract_from_dir(
        str(html.TEMPLATES),
        [("**.html", JINJA)],
        options_map={"**.html": {"extensions": "jinja2.ext.i18n"}},
    )
    code = extract_from_dir(str(Path("app/html")), [("**.py", "python")])
    return {message[2] for message in [*templates, *code]}


def test_every_string_of_the_pages_has_an_italian_translation():
    html = import_module("fastgeoapi_html")
    with (html.LOCALE / "it" / "LC_MESSAGES" / "messages.po").open("rb") as handle:
        catalog = read_po(handle)

    untranslated = sorted(
        text for text in _strings() if catalog.get(text) is None or not catalog.get(text).string
    )

    assert untranslated == []
