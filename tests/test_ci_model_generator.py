"""The sessions that generate and check the config models pin one exact generator.

The check exists to notice a change in pygeoapi's schema. With a range, a
generator release that only rewrites the same models in another form fails
it as well, on branches that touch nothing of the kind.
"""

import ast
import re
from pathlib import Path

GENERATOR = re.compile(r"^datamodel-code-generator==\d+\.\d+\.\d+$")


def _installs(session: str) -> list[str]:
    """The literal requirements a nox session in noxfile.py installs."""
    tree = ast.parse(Path("noxfile.py").read_text())
    (function,) = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == session
    ]
    return [
        argument.value
        for call in ast.walk(function)
        if isinstance(call, ast.Call) and ast.unparse(call.func) == "session.install"
        for argument in call.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
    ]


def test_both_sessions_pin_the_same_exact_generator():
    pins = [
        requirement
        for session in ("models", "models_check")
        for requirement in _installs(session)
        if requirement.startswith("datamodel-code-generator")
    ]

    assert len(pins) == 2, pins
    assert all(GENERATOR.match(pin) for pin in pins), pins
    assert pins[0] == pins[1], pins
