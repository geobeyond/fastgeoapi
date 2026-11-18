"""Which skills an OpenAPI document selects.

A skill is served when the document has an operation it teaches, so an
agent never reads about an operation it cannot call.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})
"""The keys of an OpenAPI path item that name an operation."""

LOCAL_PARAMETER = "#/components/parameters/"
"""The prefix of a reference to a parameter of the same document."""


class Operation(BaseModel):
    """An operation a skill or a file of a skill teaches.

    Attributes
    ----------
    method
        The HTTP method, in upper case.
    path
        A regular expression the whole OpenAPI path must match.
    parameter
        A parameter the operation must have, or ``None`` for any operation
        on a matching path.
    """

    model_config = ConfigDict(frozen=True)

    method: str
    path: str
    parameter: str | None = None


class FileRequirement(BaseModel):
    """What a file of a skill needs from the document, and the parameters it names.

    Attributes
    ----------
    needs
        The operations the file teaches. One of them in the document is
        enough; none at all means the file is always served.
    parameters
        The query and header parameters the text of the file names.
    """

    model_config = ConfigDict(frozen=True)

    needs: tuple[Operation, ...] = ()
    parameters: tuple[str, ...] = ()


class SkillRequirement(FileRequirement):
    """What a skill needs from the document, for its ``SKILL.md`` and optional files.

    Attributes
    ----------
    name
        The name of the skill, which is also the name of its folder.
    files
        The optional files of the skill, keyed by their path inside the
        folder. A file is served when its own needs are met.
    """

    name: str
    files: dict[str, FileRequirement] = {}


def _parameter_name(parameter: Mapping[str, Any], components: Mapping[str, Any]) -> str | None:
    """Get the name of a parameter, or of the one its ``$ref`` points to.

    A local reference takes the ``name`` of the component it points to. A
    remote one, which is not resolved here, takes the last segment of its
    path without ``.yaml``.

    Parameters
    ----------
    parameter
        A parameter of an operation, written out or as a ``$ref``.
    components
        The ``components.parameters`` of the document.

    Returns
    -------
    str or None
        The name, or ``None`` for a parameter with neither a name nor a
        reference.
    """
    if isinstance(parameter.get("name"), str):
        return parameter["name"]
    reference = parameter.get("$ref")
    if not isinstance(reference, str):
        return None
    last = reference.rsplit("/", 1)[-1]
    if reference.startswith(LOCAL_PARAMETER):
        target = components.get(last)
        if isinstance(target, Mapping) and isinstance(target.get("name"), str):
            return target["name"]
    return last.removesuffix(".yaml")


def _parameter_names(parameters: Any, components: Mapping[str, Any]) -> frozenset[str]:
    """Get the names of a list of parameters, skipping the malformed ones.

    Parameters
    ----------
    parameters
        The ``parameters`` of an operation or of a path item.
    components
        The ``components.parameters`` of the document.

    Returns
    -------
    frozenset[str]
        The names; empty when ``parameters`` is not a list.
    """
    if not isinstance(parameters, list):
        return frozenset()
    names = (_parameter_name(p, components) for p in parameters if isinstance(p, Mapping))
    return frozenset(name for name in names if name is not None)


def find_operations(openapi_spec: Mapping[str, Any]) -> list[tuple[str, str, str, frozenset[str]]]:
    """List the operations of an OpenAPI document with their parameters.

    Parameters
    ----------
    openapi_spec
        The OpenAPI document.

    Returns
    -------
    list[tuple[str, str, str, frozenset[str]]]
        For each operation: the method in upper case, the path, the
        ``operationId`` (empty when missing) and the names of its
        parameters, the ones declared on the path included.
    """
    components = (openapi_spec.get("components") or {}).get("parameters") or {}
    operations = []
    for path, item in (openapi_spec.get("paths") or {}).items():
        if not isinstance(item, Mapping):
            continue
        shared = _parameter_names(item.get("parameters"), components)
        for method, operation in item.items():
            if method not in HTTP_METHODS or not isinstance(operation, Mapping):
                continue
            names = shared | _parameter_names(operation.get("parameters"), components)
            operation_id = str(operation.get("operationId") or "")
            operations.append((method.upper(), path, operation_id, names))
    return operations


def _is_met(
    requirement: FileRequirement, operations: Sequence[tuple[str, str, str, frozenset[str]]]
) -> bool:
    """Say whether one of the operations a requirement needs is in the document.

    Parameters
    ----------
    requirement
        The requirement of a skill or of one of its files.
    operations
        The operations of the document, as :func:`find_operations` lists them.

    Returns
    -------
    bool
        ``True`` when the requirement needs nothing, or when an operation
        has the method, a matching path and, if asked, the parameter.
    """
    if not requirement.needs:
        return True
    return any(
        method == need.method
        and re.fullmatch(need.path, path) is not None
        and (need.parameter is None or need.parameter in names)
        for need in requirement.needs
        for method, path, _, names in operations
    )


def select_skills(
    openapi_spec: Mapping[str, Any], requirements: Sequence[SkillRequirement]
) -> dict[str, frozenset[str]]:
    """Select the skills, and their optional files, that a document can serve.

    Parameters
    ----------
    openapi_spec
        The OpenAPI document the MCP tools are generated from.
    requirements
        The requirement of each skill.

    Returns
    -------
    dict[str, frozenset[str]]
        The names of the selected skills, each with the optional files it
        keeps. A skill none of whose operations is in the document is absent.
    """
    operations = find_operations(openapi_spec)
    return {
        requirement.name: frozenset(
            path for path, file in requirement.files.items() if _is_met(file, operations)
        )
        for requirement in requirements
        if _is_met(requirement, operations)
    }
