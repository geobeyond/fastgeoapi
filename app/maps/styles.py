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

from app.maps.contract import MapSource

_PALETTE = ("#e15759", "#4e79a7", "#59a14f", "#f28e2b", "#76b7b2", "#b07aa1")

_SOURCES: dict[str, Callable[[str], dict[str, Any]]] = {
    # The PMTiles protocol of MapLibre reads the archive by ranged requests.
    "pmtiles": lambda url: {"type": "vector", "url": f"pmtiles://{url}"},
}


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
            raise ValueError(f"MapLibre styles cannot point at a {source.format} source")
        self._source = source
        self._translate = translate
        self._styles = dict(styles or {})
        self._default = default
        self._source_id = source_id
        self._generated: dict[str, Any] | None = None

    def names(self) -> list[str]:
        """The configured style names, sorted."""
        return sorted(self._styles)

    def style(self, name: str | None, transparent: bool) -> dict[str, Any]:
        """A copy of the style ``name``, or of the default one, pointed at the source."""
        chosen = name if name is not None else self._default
        if chosen is not None:
            base = self._styles[chosen]
        else:
            if self._generated is None:
                self._generated = default_style(self._source.layers(), self._source_id)
            base = self._generated
        style = deepcopy(base)
        style.setdefault("sources", {})[self._source_id] = self._translate(self._source.url())
        if transparent:
            style["layers"] = [
                layer for layer in style.get("layers", []) if layer.get("type") != "background"
            ]
        return style
