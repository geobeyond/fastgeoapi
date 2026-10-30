"""The native map providers of a configuration that miss a member of the contract.

A map provider class that sets ``native_async`` is awaited on the event
loop, and must define every member in
:data:`~app.interfaces.providers.NATIVE_MAP_MEMBERS`. A configuration
where one misses a member is refused at load. Otherwise the map route
would not take the provider for a native one, and would hand its maps to
pygeoapi's route in the threadpool.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.interfaces.providers import NATIVE_MAP_MEMBERS
from app.pygeoapi.plugin import resolve_provider_class


def native_map_definitions(config: dict[str, Any]) -> Iterator[tuple[str, int, dict, type]]:
    """The map provider definitions of a configuration whose class sets ``native_async``.

    Entries of another shape and classes that do not import are skipped,
    as are pygeoapi's short names.

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


def map_contract_problem(config: dict[str, Any]) -> tuple[str, str] | None:
    """Where the first native map provider misses a member, and which.

    The check reads the classes and builds no provider. Providers without
    ``native_async`` are left to pygeoapi, and so are those named with one
    of pygeoapi's short names or with a name that does not import.

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
    for name, index, provider, cls in native_map_definitions(config):
        for member in NATIVE_MAP_MEMBERS:
            if not hasattr(cls, member):
                return (
                    f"resources.{name}.providers.{index}",
                    f"{provider.get('name')} sets native_async but has no {member}",
                )
    return None
