"""The server's ceiling on map sizes, and what each native map provider accepts and draws.

The ceiling comes from the settings. A collection's provider may lower it,
never raise it.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pygeoapi import plugin as pygeoapi_plugin
from pygeoapi.provider.base import ProviderGenericError, ProviderTypeError
from pyproj import CRS
from pyproj.exceptions import CRSError

from app.config.logging import create_logger
from app.interfaces.providers import (
    MAPS_CONFORMANCE_PREFIX,
    AsyncMapProvider,
    MapCapabilities,
    MapFormat,
    MapLimits,
)
from app.pygeoapi.map_contract import iter_native_map_definitions

logger = create_logger("app.pygeoapi.map_limits")

_OGC_CRS_URIS = ("http://www.opengis.net/def/crs/", "https://www.opengis.net/def/crs/")


@dataclass(frozen=True)
class MapCeiling:
    """The largest map size, whatever the collection.

    Attributes
    ----------
    max_width
        The largest ``width`` of a map, in pixels.
    max_height
        The largest ``height`` of a map, in pixels.
    max_pixels
        The largest ``width * height``, or None for no limit on the area.
    """

    max_width: int = 2048
    max_height: int = 2048
    max_pixels: int | None = None

    @classmethod
    def from_settings(cls, settings: Any) -> MapCeiling:
        """Read the ceiling from fastgeoapi's settings.

        Parameters
        ----------
        settings
            fastgeoapi's settings; a setting they lack keeps its default.

        Returns
        -------
        MapCeiling
            The ceiling of ``FASTGEOAPI_MAPS_MAX_WIDTH``,
            ``FASTGEOAPI_MAPS_MAX_HEIGHT`` and ``FASTGEOAPI_MAPS_MAX_PIXELS``.
        """
        default = cls()
        pixels = getattr(settings, "FASTGEOAPI_MAPS_MAX_PIXELS", default.max_pixels)
        return cls(
            max_width=int(getattr(settings, "FASTGEOAPI_MAPS_MAX_WIDTH", default.max_width)),
            max_height=int(getattr(settings, "FASTGEOAPI_MAPS_MAX_HEIGHT", default.max_height)),
            max_pixels=None if pixels is None else int(pixels),
        )


def get_default_map_ceiling() -> MapCeiling:
    """Get the ceiling of fastgeoapi's settings, or the defaults without them.

    Returns
    -------
    MapCeiling
        The ceiling.
    """
    # Imported here: building the settings needs a configured fastgeoapi, and
    # the document is also built by tools that only have pygeoapi.
    try:
        from app.config.app import configuration
    except (ImportError, ValueError):
        return MapCeiling()
    return MapCeiling.from_settings(configuration)


def cut_limits_to_ceiling(limits: MapLimits, ceiling: MapCeiling) -> MapLimits:
    """Cut a provider's limits to the ceiling.

    Parameters
    ----------
    limits
        The limits the collection's provider declares.
    ceiling
        The server's ceiling.

    Returns
    -------
    MapLimits
        The smaller of each limit; a pixel limit set on one side only is
        kept.
    """
    pixels = [value for value in (limits.max_pixels, ceiling.max_pixels) if value is not None]
    return dataclasses.replace(
        limits,
        max_width=min(limits.max_width, ceiling.max_width),
        max_height=min(limits.max_height, ceiling.max_height),
        max_pixels=min(pixels) if pixels else None,
    )


def collect_native_map_limits(config: dict[str, Any], ceiling: MapCeiling) -> dict[str, MapLimits]:
    """Collect the limits of every native map provider, cut to the ceiling.

    A collection whose provider asks for more than the ceiling is logged
    once, with what it asked and what it gets.

    Parameters
    ----------
    config
        The pygeoapi configuration.
    ceiling
        The server's ceiling.

    Returns
    -------
    dict of str to MapLimits
        The limits by collection name. A provider that does not load is left
        out.
    """
    limits: dict[str, MapLimits] = {}
    for name, _, provider in _iter_native_map_providers(config):
        own = provider.limits
        cut = cut_limits_to_ceiling(own, ceiling)
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


def find_map_capability_problem(config: dict[str, Any]) -> tuple[str, str] | None:
    """Find the first native map provider whose capabilities fall outside the standard.

    A format must be one of :class:`~app.interfaces.providers.MapFormat`,
    and a CRS an OGC CRS URI that pyproj knows. A provider that does not
    load is left out, as in :func:`collect_native_map_limits`.

    Parameters
    ----------
    config
        The pygeoapi configuration.

    Returns
    -------
    tuple of (str, str) or None
        The provider's place in the configuration, as
        ``resources.<name>.providers.<index>``, and a message that names
        the class and the capability; None when every capability is valid.
    """
    for name, index, definition, _ in iter_native_map_definitions(config):
        try:
            provider = pygeoapi_plugin.load_plugin("provider", definition)
        except (KeyError, ProviderTypeError, ProviderGenericError):
            continue
        capabilities = getattr(provider, "capabilities", None)
        if not isinstance(capabilities, MapCapabilities):
            continue
        where = f"resources.{name}.providers.{index}"
        cls = definition.get("name")
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
