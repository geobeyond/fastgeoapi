"""Elevations stored as RGB tiles: the encodings MapLibre reads.

Kept apart from the PMTiles tile types so that checking a provider's
options imports nothing from the optional ``pmtiles`` extra.
"""

from __future__ import annotations

DEM_ENCODINGS = ("terrarium", "mapbox")
"""The encodings of elevations in RGB tiles that MapLibre reads."""


def check_dem(value: object) -> str | None:
    """The configured ``options.dem``; raises :class:`ValueError` if MapLibre cannot read it."""
    if value is None:
        return None
    if value not in DEM_ENCODINGS:
        raise ValueError(f"options.dem must be one of {', '.join(DEM_ENCODINGS)}, not {value}")
    return str(value)
