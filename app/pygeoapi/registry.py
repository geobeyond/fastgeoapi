"""Route registry (ADR-0005): which spec groups the config activates.

OpenAPI (``get_oas``) and conformance (fastgeoapi patch) already derive
from the configuration; the route table was the last static surface.
``active_specs`` derives the set of spec groups from the configured
resources — reusing the conformance module's ``ResourceConfig`` so the
codebase has ONE detection logic — and the factory mounts only those
groups. The reload webhook rebuilds the sub-app, so the mounted set
follows every config update.
"""

from __future__ import annotations

from app.pygeoapi.api.conformance import ResourceConfig

# Provider type → spec group, aligned with the terminology the
# conformance module inherits from pygeoapi's ``all_apis()``.
_PROVIDER_SPECS = {
    "feature": "features",
    "record": "features",
    "tile": "tiles",
    "coverage": "coverages",
    "map": "maps",
    "edr": "edr",
}


def active_specs(config: dict) -> frozenset[str]:
    """The spec groups the configured resources actually expose.

    ``core`` is always active (landing page, openapi, conformance,
    collections); every other group needs at least one resource that
    serves it.
    """
    specs = {"core"}
    for name, resource in (config.get("resources") or {}).items():
        parsed = ResourceConfig.from_config_dict(name, resource)
        if parsed.resource_type == "process":
            specs.add("processes")
        elif parsed.resource_type == "stac-collection":
            specs.add("stac")
        for provider_type in parsed.provider_types:
            spec = _PROVIDER_SPECS.get(provider_type)
            if spec is not None:
                specs.add(spec)
    return frozenset(specs)
