"""The core of the reader imports nothing outside the standard library.

Other projects are meant to vendor it, and one of them cannot install
packages at all. Imports made only for the type checker are exempt.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

CORE = Path(__file__).parent.parent / "fastgeoapi_portolan" / "catalog"
ALLOWED = set(sys.stdlib_module_names) | {"fastgeoapi_portolan"}


def _type_checking_only(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _imports(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.If) and _type_checking_only(node):
            continue
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append(node.module)
        found += _imports(node)
    return found


def test_the_core_imports_only_the_standard_library():
    modules = sorted(CORE.rglob("*.py"))
    assert modules, "the core has no modules"

    outside = {
        f"{path.relative_to(CORE)}: {name}"
        for path in modules
        for name in _imports(ast.parse(path.read_text()))
        if name.split(".")[0] not in ALLOWED
    }

    assert outside == set()
