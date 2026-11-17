"""The package depends on neither fastgeoapi nor pygeoapi."""

import ast
from pathlib import Path

PACKAGE = Path(__file__).parent.parent / "fastgeoapi_portolan"
FORBIDDEN = ("app", "pygeoapi")


def _imported(tree: ast.AST) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module)
    return names


def test_the_package_imports_neither_fastgeoapi_nor_pygeoapi():
    found = {
        f"{path.relative_to(PACKAGE)}: {name}"
        for path in PACKAGE.rglob("*.py")
        for name in _imported(ast.parse(path.read_text()))
        if name.split(".")[0] in FORBIDDEN
    }

    assert found == set()
