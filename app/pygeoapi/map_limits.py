"""The server's ceiling on map sizes, and the limits of each collection cut to it.

The ceiling comes from the settings. A collection's provider may lower
it, never raise it. The OpenAPI document publishes both: the ceiling in
``x-OGC-limits.maps``, and each collection's limits on the ``width`` and
``height`` of its map.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from pygeoapi import plugin as pygeoapi_plugin
from pygeoapi.provider.base import ProviderGenericError, ProviderTypeError

from app.config.logging import create_logger
from app.interfaces.providers import AsyncMapProvider, MapLimits
from app.pygeoapi.map_contract import native_map_definitions

logger = create_logger("app.pygeoapi.map_limits")


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
        The largest ``width * height``, or None for no limit on the product.
    """

    max_width: int = 2048
    max_height: int = 2048
    max_pixels: int | None = None

    @classmethod
    def from_settings(cls, settings: Any) -> MapCeiling:
        """The ceiling fastgeoapi's settings set.

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


def default_map_ceiling() -> MapCeiling:
    """The ceiling of fastgeoapi's settings, or the defaults without them."""
    # Imported here: building the settings needs a configured fastgeoapi, and
    # the document is also built by tools that only have pygeoapi.
    try:
        from app.config.app import configuration
    except (ImportError, ValueError):
        return MapCeiling()
    return MapCeiling.from_settings(configuration)


def collection_limits(limits: MapLimits, ceiling: MapCeiling) -> MapLimits:
    """The limits of a collection: its provider's, cut to the ceiling.

    Parameters
    ----------
    limits
        The limits the collection's provider declares.
    ceiling
        The server's ceiling.

    Returns
    -------
    MapLimits
        The smaller of each side and of the two pixel limits; the other
        fields as the provider declares them.
    """
    pixels = [value for value in (limits.max_pixels, ceiling.max_pixels) if value is not None]
    return dataclasses.replace(
        limits,
        max_width=min(limits.max_width, ceiling.max_width),
        max_height=min(limits.max_height, ceiling.max_height),
        max_pixels=min(pixels) if pixels else None,
    )


def native_map_limits(config: dict[str, Any], ceiling: MapCeiling) -> dict[str, MapLimits]:
    """The limits of every collection whose map provider is native, cut to the ceiling.

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
        out: its map fails on the route as it would without limits.
    """
    limits: dict[str, MapLimits] = {}
    for name, _, definition, _ in native_map_definitions(config):
        try:
            provider = pygeoapi_plugin.load_plugin("provider", definition)
        except (KeyError, ProviderTypeError, ProviderGenericError):
            continue
        if not isinstance(provider, AsyncMapProvider):
            continue
        own = provider.limits
        cut = collection_limits(own, ceiling)
        if cut != own:
            logger.warning(f"{name}: maps up to {_size(own)} asked, {_size(cut)} served")
        limits[name] = cut
    return limits


def _size(limits: MapLimits) -> str:
    size = f"{limits.max_width}x{limits.max_height}"
    return size if limits.max_pixels is None else f"{size} and {limits.max_pixels} pixels"
