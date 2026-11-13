"""MapLibre styles for a map collection, pointed at its source.

A MapLibre style names its data sources and says how to read each one.
The collection's source becomes one of them, under the name the
configured styles use for it, and the default style draws every layer of
it. The source's format decides the MapLibre source object, and the
styles refuse a format with no translation here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from app.maps.contract import MapSource, SourceContent, SourceNotDrawableError

_PALETTE = ("#e15759", "#4e79a7", "#59a14f", "#f28e2b", "#76b7b2", "#b07aa1")


def _pmtiles(url: str, content: SourceContent) -> dict[str, Any]:
    # The PMTiles protocol of MapLibre reads the archive by ranged requests,
    # whatever its tiles; the source type says how to draw them.
    source: dict[str, Any] = {"type": content.kind, "url": f"pmtiles://{url}"}
    if content.tile_size:
        source["tileSize"] = content.tile_size
    if content.dem:
        source["encoding"] = content.dem
    return source


_SOURCES: dict[str, Callable[[str, SourceContent], dict[str, Any]]] = {"pmtiles": _pmtiles}

# Tile encodings MapLibre Native cannot decode: a render of them fails, and
# the provider would replace the renderer at every map.
_UNDRAWABLE = {"avif": "AVIF"}


def default_style(vector_layers: Sequence[str], source: str) -> dict[str, Any]:
    """A plain MapLibre style that draws every layer of ``source``.

    Lines and polygon outlines as lines, polygons as a light fill, points
    as circles, one colour per layer, over a white background.
    """
    layers: list[dict[str, Any]] = [
        {"id": "background", "type": "background", "paint": {"background-color": "#ffffff"}}
    ]
    for index, name in enumerate(vector_layers):
        colour = _PALETTE[index % len(_PALETTE)]
        common = {"source": source, "source-layer": name}
        layers += [
            {
                "id": f"{name}-fill",
                "type": "fill",
                **common,
                "filter": ["==", ["geometry-type"], "Polygon"],
                "paint": {"fill-color": colour, "fill-opacity": 0.3},
            },
            {
                "id": f"{name}-line",
                "type": "line",
                **common,
                "paint": {"line-color": colour, "line-width": 1},
            },
            {
                "id": f"{name}-circle",
                "type": "circle",
                **common,
                "filter": ["==", ["geometry-type"], "Point"],
                "paint": {"circle-color": colour, "circle-radius": 3},
            },
        ]
    return {"version": 8, "sources": {}, "layers": layers}


def default_raster_style(source: str) -> dict[str, Any]:
    """A plain MapLibre style that draws the raster ``source`` over a white background."""
    return {
        "version": 8,
        "sources": {},
        "layers": [
            {"id": "background", "type": "background", "paint": {"background-color": "#ffffff"}},
            {"id": "raster", "type": "raster", "source": source},
        ],
    }


def default_hillshade_style(source: str) -> dict[str, Any]:
    """A plain MapLibre style that shades the relief of the elevation ``source``."""
    return {
        "version": 8,
        "sources": {},
        "layers": [
            {"id": "background", "type": "background", "paint": {"background-color": "#f2efe9"}},
            {
                "id": "hillshade",
                "type": "hillshade",
                "source": source,
                "paint": {
                    "hillshade-exaggeration": 0.6,
                    "hillshade-shadow-color": "#473b24",
                    "hillshade-highlight-color": "#ffffff",
                    "hillshade-accent-color": "#6b5b45",
                },
            },
        ],
    }


class MapLibreStyles:
    """The MapLibre styles of one map collection."""

    def __init__(
        self,
        source: MapSource,
        styles: Mapping[str, dict[str, Any]] | None = None,
        *,
        default: str | None = None,
        source_id: str = "archive",
    ) -> None:
        """``source_id`` is the name the styles give the collection's source."""
        translate = _SOURCES.get(source.format)
        if translate is None:
            raise SourceNotDrawableError(
                f"MapLibre styles cannot point at a {source.format} source"
            )
        self._source = source
        self._translate = translate
        # Kept as given: a lazy mapping reads each style only when it is drawn.
        self._styles = styles if styles is not None else {}
        self._default = default
        self._source_id = source_id
        self._generated: dict[str, Any] | None = None

    def names(self) -> list[str]:
        """The configured style names, sorted."""
        return sorted(self._styles)

    def style(self, name: str | None, transparent: bool) -> dict[str, Any]:
        """A copy of the style ``name``, or of the default one, pointed at the source.

        A style that declares its source with a type keeps that source and its
        settings, and the data is not read for it.
        """
        chosen = name if name is not None else self._default
        if chosen is not None:
            base = self._styles[chosen]
        else:
            if self._generated is None:
                content = self._source.content()
                if content.kind == "raster":
                    self._generated = default_raster_style(self._source_id)
                elif content.kind == "raster-dem":
                    self._generated = default_hillshade_style(self._source_id)
                else:
                    self._generated = default_style(list(content.layers), self._source_id)
            base = self._generated
        style = deepcopy(base)
        sources = style.setdefault("sources", {})
        declared = sources.get(self._source_id) or {}
        if "type" in declared:
            content = SourceContent(declared["type"], tile_size=declared.get("tileSize"))
        else:
            content = self._source.content()
        if content.encoding in _UNDRAWABLE:
            raise SourceNotDrawableError(
                f"MapLibre Native cannot draw {_UNDRAWABLE[content.encoding]} tiles"
            )
        sources[self._source_id] = {**declared, **self._translate(self._source.url(), content)}
        if transparent:
            style["layers"] = [
                layer for layer in style.get("layers", []) if layer.get("type") != "background"
            ]
        return style


def create_maplibre_styles(
    source: MapSource, documents: Mapping[str, dict[str, Any]], options: Mapping[str, Any]
) -> MapLibreStyles:
    """The MapLibre styles of a map provider: the default ``style_factory``.

    ``options`` gives the default style (``default_style``) and the name the
    styles give the collection's source (``style_source``).
    """
    return MapLibreStyles(
        source,
        documents,
        default=options.get("default_style"),
        source_id=options.get("style_source", "archive"),
    )
