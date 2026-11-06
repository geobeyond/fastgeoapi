"""Checking catalog documents against the STAC, Portolan and extension schemas the package ships.

The validator reads every schema from the package and never goes to the
network. A declared schema the package does not ship is listed as
unverified, and the rest of the document is still checked.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError, best_match
from jsonschema.protocols import Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

from fastgeoapi_portolan.catalog.results import Finding, Validation
from fastgeoapi_portolan.catalog.schema_files import schema_resources
from fastgeoapi_portolan.catalog.walk import PORTOLAN_SCHEMAS, declared_profile

_STAC = "https://schemas.stacspec.org/v"
_KINDS = {"Catalog": "catalog", "Collection": "collection", "Feature": "item"}
# The STAC version a document without a usable `stac_version` is held to.
_DEFAULT_STAC_VERSION = "1.1.0"
# A message can quote the whole instance.
_MAX_MESSAGE = 300


def _wrong_kind(error: ValidationError) -> bool:
    return error.validator in ("const", "enum") and list(error.absolute_path) == ["type"]


def _cause(error: ValidationError) -> ValidationError:
    """The error that names what fails, below the ``oneOf`` and ``anyOf`` that wrap it.

    The Portolan profile is a ``oneOf`` over catalogs, collections and
    items: the branches for the other two kinds fail on ``type``, so they
    are set aside before choosing.
    """
    while error.context:
        branches: dict[Any, list[ValidationError]] = {}
        for sub in error.context:
            branches.setdefault(sub.schema_path[0] if sub.schema_path else None, []).append(sub)
        right_kind = [errors for errors in branches.values() if not any(map(_wrong_kind, errors))]
        cause = best_match(min(right_kind, key=len) if right_kind else error.context)
        if cause is None:
            break
        error = cause
    return error


def _pointer(error: ValidationError) -> str:
    """The JSON Pointer (RFC 6901) of the failing value; empty at the document root."""
    return "".join(
        "/" + str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path
    )


def _finding(error: ValidationError, schema: str) -> Finding:
    cause = _cause(error)
    message = cause.message
    if len(message) > _MAX_MESSAGE:
        message = f"{message[: _MAX_MESSAGE - 3]}..."
    return Finding(_pointer(cause), message, schema)


class JsonSchemaValidator:
    """Checks a document against the STAC core schema, its Portolan profile and its extensions.

    The profile is the Portolan schema the document declares, or else the
    root's. Building the validator loads every shipped schema, so build it
    once and reuse it.
    """

    def __init__(self) -> None:
        resources = [
            (uri, Resource.from_contents(contents, default_specification=DRAFT7))
            for uri, contents in schema_resources()
        ]
        self._registry: Registry = Registry().with_resources(resources).crawl()
        self._shipped = frozenset(uri for uri, _ in resources)
        self._validators: dict[str, Validator] = {}

    def _validator(self, schema: str) -> Validator:
        if schema not in self._validators:
            self._validators[schema] = Draft7Validator({"$ref": schema}, registry=self._registry)
        return self._validators[schema]

    def validate(self, document: Mapping[str, Any], *, root_profile: str | None) -> Validation:
        """The schema errors in ``document``, and the declared schemas left unchecked."""
        findings: list[Finding] = []
        version = document.get("stac_version")
        if not isinstance(version, str):
            version = _DEFAULT_STAC_VERSION
        kind = _KINDS.get(str(document.get("type")))
        schemas: list[str] = []
        if kind is None:
            findings.append(
                Finding(
                    "/type",
                    f"{document.get('type')!r} is not one of 'Catalog', 'Collection', 'Feature'",
                    f"{_STAC}{version}/",
                )
            )
        else:
            schemas.append(f"{_STAC}{version}/{kind}-spec/json-schema/{kind}.json")
        profile = declared_profile(document) or root_profile
        if profile:
            schemas.append(profile)
        extensions = document.get("stac_extensions")
        if isinstance(extensions, list):
            schemas += [
                uri
                for uri in extensions
                if isinstance(uri, str) and not uri.startswith(PORTOLAN_SCHEMAS)
            ]
        unverified: dict[str, None] = {}
        for schema in schemas:
            if schema.split("#", 1)[0] not in self._shipped:
                unverified[schema] = None
                continue
            findings += [
                _finding(error, schema) for error in self._validator(schema).iter_errors(document)
            ]
        return Validation(tuple(findings), tuple(unverified))
