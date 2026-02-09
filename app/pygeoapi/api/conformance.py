"""Override module for pygeoapi conformance endpoint.

This module provides a corrected implementation of the conformance function
that dynamically builds the conformance classes list based on the actual
server configuration, avoiding the upstream bug where the global list
is mutated on each request.

Architecture follows the project typing patterns:
- Protocol (Static Duck Typing): ConformanceProvider for loose coupling
  (defined in app.interfaces.conformance)
- Dataclass (Static Nominal): ConformanceResponse as immutable value object
- Service function: build_conformance_list for business logic

See: https://github.com/geopython/pygeoapi/issues/XXXX
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

from pygeoapi.api import (
    CONFORMANCE_CLASSES,
    F_HTML,
    all_apis,
    to_json,
)
from pygeoapi.util import render_j2_template

if TYPE_CHECKING:
    from pygeoapi.api import API, APIRequest


# =============================================================================
# STATIC NOMINAL: Domain value objects
# =============================================================================


@dataclass(frozen=True, slots=True)
class ConformanceResponse:
    """Immutable value object representing a conformance response.

    frozen=True: Ensures immutability for thread safety
    slots=True: Memory efficiency
    """

    conforms_to: tuple[str, ...]

    def to_dict(self) -> dict[str, list[str]]:
        """Convert to OGC API compliant dictionary format."""
        return {"conformsTo": list(self.conforms_to)}


@dataclass(frozen=True, slots=True)
class ResourceConfig:
    """Value object representing a resource configuration.

    Extracts relevant configuration for conformance determination.
    """

    name: str
    resource_type: str
    provider_types: tuple[str, ...]

    @classmethod
    def from_config_dict(cls, name: str, config: dict) -> ResourceConfig:
        """Create ResourceConfig from pygeoapi config dictionary."""
        resource_type = config.get("type", "")
        providers = config.get("providers", [])
        provider_types = tuple(p.get("type", "") for p in providers)
        return cls(
            name=name,
            resource_type=resource_type,
            provider_types=provider_types,
        )


# =============================================================================
# SERVICE: Conformance building logic
# =============================================================================


def get_provider_conformance(
    provider_type: str,
    apis_dict: dict[str, GenericConformance],
    itemtypes_module: FeatureRecordConformance,
) -> list[str]:
    """Get conformance classes for a specific provider type.

    :param provider_type: The provider type (feature, coverage, tile, etc.)
    :param apis_dict: Dictionary mapping provider types to API modules
    :param itemtypes_module: The itemtypes module for feature/record specifics

    :returns: List of conformance class URIs
    """
    classes: list[str] = []

    if provider_type in apis_dict:
        classes.extend(apis_dict[provider_type].CONFORMANCE_CLASSES)

    if provider_type == "feature":
        classes.extend(itemtypes_module.CONFORMANCE_CLASSES_FEATURES)
    elif provider_type == "record":
        classes.extend(itemtypes_module.CONFORMANCE_CLASSES_RECORDS)

    return classes


def build_conformance_list(
    resources: dict[str, dict],
    has_pubsub: bool,
) -> ConformanceResponse:
    """Build the conformance classes list based on configured resources.

    This function implements the core logic for determining which conformance
    classes should be advertised based on the server configuration.

    :param resources: Dictionary of resource configurations from pygeoapi config
    :param has_pubsub: Whether PubSub is configured

    :returns: ConformanceResponse with deduplicated, sorted conformance classes
    """
    apis_dict = all_apis()
    itemtypes_module = apis_dict["itemtypes"]

    # CRITICAL FIX: Create a copy to avoid mutating the global list
    conformance_set: set[str] = set(CONFORMANCE_CLASSES)

    for name, config in resources.items():
        resource = ResourceConfig.from_config_dict(name, config)

        if resource.resource_type == "process":
            conformance_set.update(apis_dict["process"].CONFORMANCE_CLASSES)
        else:
            for provider_type in resource.provider_types:
                provider_classes = get_provider_conformance(
                    provider_type, apis_dict, itemtypes_module
                )
                conformance_set.update(provider_classes)

    if has_pubsub:
        conformance_set.update(apis_dict["pubsub"].CONFORMANCE_CLASSES)

    return ConformanceResponse(conforms_to=tuple(sorted(conformance_set)))


# =============================================================================
# API ENDPOINT: Starlette-compatible handler
# =============================================================================


def conformance(api: API, request: APIRequest) -> tuple[dict, int, str]:
    """Provide conformance definition based on configured resources.

    This is a corrected version of pygeoapi.api.conformance that:
    1. Creates a copy of the base conformance classes to avoid mutating the global
    2. Only includes conformance classes for API types that are actually configured
    3. Uses immutable value objects for thread safety

    :param api: API instance
    :param request: APIRequest instance

    :returns: tuple of headers, status code, content
    """
    response = build_conformance_list(
        resources=api.config["resources"],
        has_pubsub=api.pubsub_client is not None,
    )

    headers = request.get_response_headers(**api.api_headers)

    if request.format == F_HTML:
        content = render_j2_template(
            api.tpl_config,
            api.config["server"]["templates"],
            "conformance.html",
            response.to_dict(),
            request.locale,
        )
        return headers, HTTPStatus.OK, content

    return headers, HTTPStatus.OK, to_json(response.to_dict(), api.pretty_print)
