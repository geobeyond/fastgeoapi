"""The native map providers of a configuration that miss a member of the contract.

A map provider class that sets ``native_async`` is awaited on the event
loop, and must define every member in
:data:`~app.interfaces.providers.NATIVE_MAP_MEMBERS`. A configuration
where one misses a member is refused at load. Otherwise the map route
would not take the provider for a native one, and would hand its maps to
pygeoapi's route in the threadpool.
"""

from __future__ import annotations

from typing import Any

from app.interfaces.providers import NATIVE_MAP_MEMBERS
from app.pygeoapi.plugin import resolve_provider_class


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
    resources = config.get("resources")
    for name, resource in (resources if isinstance(resources, dict) else {}).items():
        if not isinstance(resource, dict):
            continue
        for index, provider in enumerate(resource.get("providers") or []):
            if not isinstance(provider, dict) or provider.get("type") != "map":
                continue
            dotted = str(provider.get("name", ""))
            cls = resolve_provider_class(dotted)
            if cls is None or not getattr(cls, "native_async", False):
                continue
            for member in NATIVE_MAP_MEMBERS:
                if not hasattr(cls, member):
                    return (
                        f"resources.{name}.providers.{index}",
                        f"{dotted} sets native_async but has no {member}",
                    )
    return None
