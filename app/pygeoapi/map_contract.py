"""The check that every native map provider of a configuration defines the whole contract.

A map provider class that sets ``native_async`` must define every member of
:class:`~app.interfaces.providers.AsyncMapProvider`; a configuration that
names one missing a member is refused when it loads.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from typing_extensions import get_protocol_members

from app.interfaces.providers import AsyncMapProvider
from app.pygeoapi.plugin import resolve_provider_class


def iter_native_map_definitions(config: dict[str, Any]) -> Iterator[tuple[str, int, dict, type]]:
    """Yield the map provider definitions whose class sets ``native_async``.

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
            if not isinstance(provider, dict) or provider.get("type") != "map":
                continue
            cls = resolve_provider_class(str(provider.get("name", "")))
            if cls is not None and getattr(cls, "native_async", False):
                yield name, index, provider, cls


def find_map_contract_problem(config: dict[str, Any]) -> tuple[str, str] | None:
    """Find the first native map provider that misses a member of the contract.

    Only classes that set ``native_async`` are checked. The check reads the
    classes and builds no provider.

    Parameters
    ----------
    config
        The pygeoapi configuration; entries of another shape are skipped.

    Returns
    -------
    tuple of (str, str) or None
        The provider's place in the configuration, as
        ``resources.<name>.providers.<index>``, and a message that names
        the class and the missing member; None when every native map
        provider has all the members.
    """
    for name, index, provider, cls in iter_native_map_definitions(config):
        for member in sorted(get_protocol_members(AsyncMapProvider)):
            if not hasattr(cls, member):
                return (
                    f"resources.{name}.providers.{index}",
                    f"{provider.get('name')} sets native_async but has no {member}",
                )
    return None
