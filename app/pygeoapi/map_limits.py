"""The server's limits on map sizes, and what each native map provider accepts and draws.

The server's limits come from the settings. A collection's provider may
lower them, never raise them.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from pygeoapi import plugin as pygeoapi_plugin
from pygeoapi.provider.base import ProviderGenericError, ProviderTypeError
from pyproj import CRS
from pyproj.exceptions import CRSError

from app.config.logging import create_logger
from app.interfaces.ogc import MAPS_CONFORMANCE_PREFIX
from app.interfaces.providers import (
    AsyncMapProvider,
    MapCapabilities,
    MapFormat,
    MapLimits,
)
from app.pygeoapi.map_contract import iter_native_map_definitions

if TYPE_CHECKING:
    from app.config.app import DevConfig, ProdConfig

logger = create_logger("app.pygeoapi.map_limits")

# The defaults of FASTGEOAPI_MAPS_MAX_WIDTH, _HEIGHT and _PIXELS, for when
# fastgeoapi's settings cannot be built.
_DEFAULT_SERVER_MAP_LIMITS: tuple[int, int, int | None] = (2048, 2048, None)

_OGC_CRS_URIS = ("http://www.opengis.net/def/crs/", "https://www.opengis.net/def/crs/")


def get_server_map_limits(
    settings: DevConfig | ProdConfig | None,
) -> tuple[int, int, int | None]:
    """Get the server's largest map from fastgeoapi's settings.

    Parameters
    ----------
    settings
        fastgeoapi's settings; None takes those of the running server, or
        their defaults when they cannot be built.

    Returns
    -------
    tuple of (int, int, int or None)
        The largest ``width`` and ``height`` in pixels, and the largest
        ``width * height`` or None for no limit.
    """
    if settings is None:
        # Imported here: building the settings needs a configured fastgeoapi,
        # and the document is also built by tools that only have pygeoapi.
        try:
            from app.config.app import configuration
        except (ImportError, ValueError):
            return _DEFAULT_SERVER_MAP_LIMITS
        if configuration is None:
            return _DEFAULT_SERVER_MAP_LIMITS
        settings = configuration
    return (
        settings.FASTGEOAPI_MAPS_MAX_WIDTH,
        settings.FASTGEOAPI_MAPS_MAX_HEIGHT,
        settings.FASTGEOAPI_MAPS_MAX_PIXELS,
    )


def clamp_provider_map_limits(
    provider_limits: MapLimits, max_width: int, max_height: int, max_pixels: int | None
) -> MapLimits:
    """Clamp a provider's map limits to the server's.

    Parameters
    ----------
    provider_limits
        The limits the collection's provider declares.
    max_width
        The server's largest ``width``, in pixels.
    max_height
        The server's largest ``height``, in pixels.
    max_pixels
        The server's largest ``width * height``, or None for no limit.

    Returns
    -------
    MapLimits
        The smaller of each limit; a pixel limit set on one side only is
        kept.
    """
    pixels = [value for value in (provider_limits.max_pixels, max_pixels) if value is not None]
    return dataclasses.replace(
        provider_limits,
        max_width=min(provider_limits.max_width, max_width),
        max_height=min(provider_limits.max_height, max_height),
        max_pixels=min(pixels) if pixels else None,
    )


def collect_native_map_limits(
    config: dict[str, Any], max_width: int, max_height: int, max_pixels: int | None
) -> dict[str, MapLimits]:
    """Collect the limits of every native map provider, clamped to the server's.

    A collection whose provider asks for more than the server allows is
    logged once, with what it asked and what it gets.

    Parameters
    ----------
    config
        The pygeoapi configuration.
    max_width
        The server's largest ``width``, in pixels.
    max_height
        The server's largest ``height``, in pixels.
    max_pixels
        The server's largest ``width * height``, or None for no limit.

    Returns
    -------
    dict of str to MapLimits
        The limits by collection name. A provider that does not load is left
        out.
    """
    limits: dict[str, MapLimits] = {}
    for name, _, provider in _iter_native_map_providers(config):
        own = provider.limits
        cut = clamp_provider_map_limits(own, max_width, max_height, max_pixels)
        if cut != own:
            logger.warning(
                f"{name}: maps up to {_describe_size(own)} asked, {_describe_size(cut)} served"
            )
        limits[name] = cut
    return limits


def collect_native_map_capabilities(config: dict[str, Any]) -> dict[str, MapCapabilities]:
    """Collect the capabilities of every native map provider.

    Parameters
    ----------
    config
        The pygeoapi configuration.

    Returns
    -------
    dict of str to MapCapabilities
        The capabilities by collection name. A provider that does not load
        is left out, as in :func:`collect_native_map_limits`.
    """
    return {name: provider.capabilities for name, _, provider in _iter_native_map_providers(config)}


_UNRESOLVED = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
"""A ``${VAR}`` of the configuration that has not been resolved yet."""


def derive_map_conformance(capabilities: MapCapabilities) -> tuple[str, ...]:
    """Derive the OGC API - Maps classes the route passes with a provider's capabilities.

    Parameters
    ----------
    capabilities
        The capabilities of a native map provider.

    Returns
    -------
    tuple of str
        ``core``, ``collection-map``, ``crs`` and the class of each
        encoding the provider draws.
    """
    # scaling, spatial-subsetting and background stay out until the route reads
    # scale-denominator, center, a spatial subset, bgcolor and void-color.
    encodings = tuple(MapFormat(format_).conformance_class for format_ in capabilities.formats)
    return (
        f"{MAPS_CONFORMANCE_PREFIX}/core",
        f"{MAPS_CONFORMANCE_PREFIX}/collection-map",
        f"{MAPS_CONFORMANCE_PREFIX}/crs",
        *encodings,
    )


def validate_map_provider_or_problem(config: dict[str, Any]) -> tuple[str, str] | None:
    """Validate the capabilities of every native map provider against the standard.

    A format must be one of :class:`~app.interfaces.providers.MapFormat`,
    and a CRS an OGC CRS URI that pyproj knows. A provider that does not
    load is left out, as in :func:`collect_native_map_limits`, and so is a
    definition that still holds a ``${VAR}``: it is built to read its
    capabilities, which it can do once the variable is resolved.

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
    for name, index, definition, _ in iter_native_map_definitions(config):
        if _UNRESOLVED.search(json.dumps(definition, default=str)):
            continue
        where = f"resources.{name}.providers.{index}"
        cls = definition.get("name")
        try:
            provider = pygeoapi_plugin.load_plugin("provider", definition)
        except (KeyError, ProviderTypeError, ProviderGenericError):
            continue
        except (ValueError, TypeError) as error:
            return where, f"{cls} cannot be built from its options: {error}"
        capabilities = getattr(provider, "capabilities", None)
        if not isinstance(capabilities, MapCapabilities):
            continue
        for format_ in capabilities.formats:
            if format_ not in set(MapFormat):
                return where, f"{cls} draws {format_}, which is not a format of OGC API - Maps"
        for crs in capabilities.crs:
            if not _is_ogc_crs_uri(crs):
                return where, f"{cls} names the CRS {crs}, which is not an OGC CRS URI"
    return None


def _is_ogc_crs_uri(value: str) -> bool:
    """Tell whether ``value`` is an OGC CRS URI that pyproj knows.

    Parameters
    ----------
    value
        The CRS to check.

    Returns
    -------
    bool
        True for an OGC CRS URI that pyproj can build a CRS from.
    """
    if not str(value).startswith(_OGC_CRS_URIS):
        return False
    try:
        CRS.from_user_input(value)
    except CRSError:
        return False
    return True


def choose_default_map_crs(provider_def: dict[str, Any], capabilities: MapCapabilities) -> str:
    """Choose the CRS of a map whose request names none.

    Parameters
    ----------
    provider_def
        The definition of the collection's map provider.
    capabilities
        The provider's capabilities.

    Returns
    -------
    str
        The ``storage_crs`` when the provider draws in it, written as the
        provider writes it; otherwise the provider's first CRS.
    """
    storage = str(provider_def.get("storage_crs", "")).lower()
    for crs in capabilities.crs:
        if crs.lower() == storage:
            return crs
    return capabilities.crs[0]


def _iter_native_map_providers(
    config: dict[str, Any],
) -> Iterator[tuple[str, dict, AsyncMapProvider]]:
    """Load the native map provider of each collection.

    Only a collection's first map provider is loaded, since it is the one
    its maps are drawn with.

    Parameters
    ----------
    config
        The pygeoapi configuration.

    Yields
    ------
    tuple of (str, dict, AsyncMapProvider)
        The collection's name, the provider's definition and the provider.
    """
    for name, index, definition, _ in iter_native_map_definitions(config):
        providers = config["resources"][name].get("providers") or []
        first = next(
            i for i, p in enumerate(providers) if isinstance(p, dict) and p.get("type") == "map"
        )
        if index != first:
            continue
        try:
            provider = pygeoapi_plugin.load_plugin("provider", definition)
        except (KeyError, ProviderTypeError, ProviderGenericError):
            continue
        if isinstance(provider, AsyncMapProvider):
            yield name, definition, provider


def _describe_size(limits: MapLimits) -> str:
    size = f"{limits.max_width}x{limits.max_height}"
    return size if limits.max_pixels is None else f"{size} and {limits.max_pixels} pixels"
