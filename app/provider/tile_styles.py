"""MapLibre styles for a collection's tiles, for the pages that draw them.

The tiles are read through the collection's TileJSON, which MapLibre
takes as a source as it is. The styles come, in this order, from the
collection's map provider, from the ``styles`` or the ``style`` option of
its tile provider, or from the tiles themselves, as the maps draw a
collection that has no style of its own.

A style document is kept for ``STYLE_TTL_SECONDS`` after it is read, so a
page does not fetch it from its store on every request.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from time import monotonic
from typing import Any

from app.config.logging import create_logger
from app.maps.styles import default_hillshade_style, default_raster_style, default_style
from app.provider.maps import read_style
from app.tiles.contract import TileContent

logger = create_logger("app.provider.tile_styles")

DEFAULT_SOURCE = "archive"
"""The name a style gives the collection's tiles, unless ``style_source`` says otherwise."""

_SOURCE_TYPES = {"vector": "vector", "map": "raster", "coverage": "raster-dem"}

# Keys of a declared source that say where its tiles are: the TileJSON replaces them.
_ADDRESS_KEYS = ("url", "tiles")

STYLE_TTL_SECONDS = 60
"""How long a style document is used before it is read again."""

# (location, store options) -> (when it was read, the document read).
_styles: dict[tuple[str, frozenset], tuple[float, Any]] = {}
_styles_lock = threading.Lock()


@dataclass(frozen=True)
class TileStyle:
    """One style a page can draw the collection's tiles with."""

    name: str | None
    """The configured name, or None for the style made from the tiles."""
    document: dict[str, Any]
    """The MapLibre style, with the collection's source pointed at the TileJSON."""


def tile_source(tilejson_url: str, content: TileContent) -> dict[str, Any]:
    """The MapLibre source of the collection's tiles, read through their TileJSON."""
    source: dict[str, Any] = {"type": _SOURCE_TYPES[content.data_type], "url": tilejson_url}
    if content.data_type != "vector" and content.tile_size:
        source["tileSize"] = content.tile_size
    if content.dem is not None:
        source["encoding"] = content.dem
    return source


def tile_styles(
    collection: dict[str, Any], tilejson_url: str, content: TileContent
) -> list[TileStyle]:
    """The styles for the collection's tiles, the default first; never empty.

    The configured styles come from the collection's map provider, or else
    from the ``styles`` or the ``style`` option of its tile provider. A
    style that cannot be read is left out with a warning; when none is
    left, the style is made from the tiles. Style documents are read here,
    so call it off the event loop.
    """
    source = tile_source(tilejson_url, content)
    providers = collection.get("providers") or []
    for configured in (_map_styles(providers), _tile_provider_styles(providers)):
        styles = [
            TileStyle(name, _pointed(document, source_id, source))
            for name, document, source_id in configured
        ]
        if styles:
            return styles
    return [TileStyle(None, _pointed(_made_from(content), DEFAULT_SOURCE, source))]


def _map_styles(providers: list[dict]) -> Iterator[tuple[str, dict, str]]:
    """The readable styles of the first map provider, its default style first."""
    for provider in providers:
        if provider.get("type") == "map":
            yield from _named_styles(provider)
            return


def _tile_provider_styles(providers: list[dict]) -> Iterator[tuple[str, dict, str]]:
    """The readable styles of the first tile provider.

    They are its ``styles``, the default first, or else its ``style``,
    named after its file.
    """
    for provider in providers:
        if provider.get("type") != "tile":
            continue
        options = provider.get("options") or {}
        if options.get("styles"):
            yield from _named_styles(provider)
        elif location := options.get("style"):
            name = PurePosixPath(location).stem
            document = _read(name, location, provider.get("store_options"))
            if document is not None:
                yield name, document, options.get("style_source") or DEFAULT_SOURCE
        return


def _named_styles(provider: dict) -> Iterator[tuple[str, dict, str]]:
    """The readable ``styles`` of a provider, its ``default_style`` first."""
    options = provider.get("options") or {}
    locations = dict(options.get("styles") or {})
    default = options.get("default_style")
    source_id = options.get("style_source") or DEFAULT_SOURCE
    # Sorting is stable: the default goes first, the others keep their order.
    for name in sorted(locations, key=lambda name: name != default):
        document = _read(name, locations[name], provider.get("store_options"))
        if document is not None:
            yield name, document, source_id


def _read_kept(location: str, store_options: dict | None) -> Any:
    """The style document at ``location``, read again once it is older than the TTL.

    A read that fails raises and is not kept.
    """
    key = (location, frozenset((store_options or {}).items()))
    now = monotonic()
    with _styles_lock:
        kept = _styles.get(key)
    if kept is not None and now - kept[0] < STYLE_TTL_SECONDS:
        return kept[1]
    document = read_style(location, store_options)
    with _styles_lock:
        _styles[key] = (now, document)
    return document


def _read(name: str, location: str, store_options: dict | None) -> dict | None:
    try:
        document = _read_kept(location, store_options)
    except Exception as error:
        # The type only: the message of a store error may name the object.
        logger.warning(f"style {name} could not be read: {type(error).__name__}")
        return None
    if not isinstance(document, dict) or not isinstance(document.get("sources", {}), dict):
        logger.warning(f"style {name} is not a MapLibre style")
        return None
    return document


def _pointed(document: dict, source_id: str, source: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``document`` whose ``source_id`` source reads the collection's tiles."""
    style = deepcopy(document)
    sources = style.setdefault("sources", {})
    declared = {
        key: value
        for key, value in (sources.get(source_id) or {}).items()
        if key not in _ADDRESS_KEYS
    }
    sources[source_id] = {**declared, **source}
    return style


def _made_from(content: TileContent) -> dict[str, Any]:
    """The style the maps draw a collection without a style of its own with."""
    if content.data_type == "vector":
        return default_style([layer.id for layer in content.layers], DEFAULT_SOURCE)
    if content.dem is not None:
        return default_hillshade_style(DEFAULT_SOURCE)
    return default_raster_style(DEFAULT_SOURCE)
