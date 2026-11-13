"""The stylesheet of the pages: every font size comes from a variable.

No ``app.*`` import in this module: it reads the stylesheet's source.
"""

import re
from pathlib import Path

STYLE = Path("frontend/pages/style.css").read_text()

DEFINITIONS = re.compile(r"(?::root|body\.dense)\s*\{([^}]*)\}")
"""The blocks that set the variables: the sizes of the pages of cards, then of the dense ones."""


def test_every_font_size_of_the_rules_comes_from_a_variable():
    rules = DEFINITIONS.sub("", STYLE)
    literal = [
        declaration
        for declaration in re.findall(r"(?:font-size|font):[^;]+;", rules)
        if "var(" not in declaration and "inherit" not in declaration
    ]

    assert literal == []


def test_the_dense_pages_redefine_the_sizes_of_their_data():
    dense = re.search(r"body\.dense\s*\{([^}]*)\}", STYLE)

    assert dense is not None
    for variable in (
        "--fga-size-body: 16px",
        "--fga-size-h1: 32px",
        "--fga-size-field: 15px",
        "--fga-size-table: 15px",
        "--fga-pad-cell: 8px 12px",
    ):
        assert variable in dense.group(1), variable
