"""The check that every native EDR provider of a configuration defines the whole contract.

An EDR provider class that sets ``native_async`` must define every member of
:class:`~app.interfaces.providers.AsyncEdrProvider`; a configuration that
names one missing a member, or one whose capabilities break the standard, is
refused when it loads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from pygeoapi import plugin as pygeoapi_plugin
from pygeoapi.provider.base import BaseProvider, ProviderGenericError, ProviderTypeError
from typing_extensions import get_protocol_members

from app.interfaces.ogc import OGC_CRS_CRS84
from app.interfaces.providers import AsyncEdrProvider, EdrCapabilities, EdrFormat
from app.pygeoapi.plugin import resolve_provider_class

_QUERY_TYPES = ("position", "area")
_UNRESOLVED = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")


def iter_native_edr_definitions(config: dict[str, Any]) -> Iterator[tuple[str, int, dict, type]]:
    """Yield the EDR provider definitions whose class sets ``native_async``.

    Entries of another shape, classes that do not import and pygeoapi's
    short names are skipped.

    Parameters
    ----------
    config
        The pygeoapi configuration.

    Yields
    ------
    tuple of (str, int, dict, type)
        The collection's name, the provider's index in its ``providers``,
        the provider's definition and its class.
    """
    resources = config.get("resources")
    for name, resource in (resources if isinstance(resources, dict) else {}).items():
        if not isinstance(resource, dict):
            continue
        for index, provider in enumerate(resource.get("providers") or []):
            if not isinstance(provider, dict) or provider.get("type") != "edr":
                continue
            cls = resolve_provider_class(str(provider.get("name", "")))
            if cls is not None and getattr(cls, "native_async", False):
                yield name, index, provider, cls


def validate_edr_contract_or_problem(config: dict[str, Any]) -> tuple[str, str] | None:
    """Validate that every native EDR provider has the members of the contract.

    Only classes that set ``native_async`` are checked. The check reads the
    classes and builds no provider.

    Parameters
    ----------
    config
        The pygeoapi configuration; entries of another shape are skipped.

    Returns
    -------
    tuple of (str, str) or None
        The place of the first provider that misses a member, as
        ``resources.<name>.providers.<index>``, and a message that names
        the class and the missing member; None when every native EDR
        provider has all the members.
    """
    for name, index, provider, cls in iter_native_edr_definitions(config):
        for member in sorted(get_protocol_members(AsyncEdrProvider)):
            if not hasattr(cls, member):
                return (
                    f"resources.{name}.providers.{index}",
                    f"{provider.get('name')} sets native_async but has no {member}",
                )
    return None


def validate_edr_provider_or_problem(config: dict[str, Any]) -> tuple[str, str] | None:
    """Validate the capabilities of every native EDR provider against this phase.

    The query types are ``position`` and ``area``, the formats are
    :class:`~app.interfaces.providers.EdrFormat` members, CRS84 is among the
    CRSs and the default CRS is one of them. A provider that does not load is
    left out, and so is a definition that still holds a ``${VAR}``: it is
    built to read its capabilities, which it can do once the variable is
    resolved.

    Parameters
    ----------
    config
        The pygeoapi configuration.

    Returns
    -------
    tuple of (str, str) or None
        The place of the first provider that cannot be built from its
        options or has an invalid capability, as
        ``resources.<name>.providers.<index>``, and a message that names
        the class and the problem; None when every capability is valid.
    """
    for name, index, definition, _ in iter_native_edr_definitions(config):
        where = f"resources.{name}.providers.{index}"
        cls = definition.get("name")
        provider, problem = _build_provider_or_problem(definition, where)
        if problem:
            return problem
        capabilities = getattr(provider, "capabilities", None)
        if not isinstance(capabilities, EdrCapabilities):
            continue
        for query_type in capabilities.query_types:
            if query_type not in _QUERY_TYPES:
                return (
                    where,
                    f"{cls} offers the {query_type} query, which this server does not serve",
                )
        for format_ in capabilities.formats:
            if not isinstance(format_, EdrFormat):
                return where, f"{cls} answers in {format_!r}, which is not an EdrFormat"
        if OGC_CRS_CRS84 not in capabilities.crs:
            return where, f"{cls} does not offer CRS84 ({OGC_CRS_CRS84}) among its CRSs"
        if capabilities.default_crs not in capabilities.crs:
            default = capabilities.default_crs
            return where, f"{cls} answers by default in {default}, which is not among its CRSs"
    return None


def _build_provider_or_problem(
    definition: dict[str, Any], where: str
) -> tuple[BaseProvider | None, tuple[str, str] | None]:
    """Build the provider of a definition, to read what it declares.

    A definition that still holds a ``${VAR}`` is not built: it can be once
    the variable is resolved. A provider that does not load is left out.

    Parameters
    ----------
    definition
        The provider's definition.
    where
        The place of the definition, as ``resources.<name>.providers.<index>``.

    Returns
    -------
    tuple of (BaseProvider or None, tuple of (str, str) or None)
        The provider and None; or None and the place with a message that
        names the class, when the options do not fit the class; or two None
        when the definition is skipped.
    """
    if _UNRESOLVED.search(json.dumps(definition, default=str)):
        return None, None
    try:
        return pygeoapi_plugin.load_plugin("provider", definition), None
    except (KeyError, ProviderTypeError, ProviderGenericError):
        return None, None
    except (ValueError, TypeError) as error:
        return None, (where, f"{definition.get('name')} cannot be built from its options: {error}")
