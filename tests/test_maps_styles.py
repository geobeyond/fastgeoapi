"""MapLibre styles for a map collection, composed with any map source."""

import pytest

from app.maps.contract import MapStyles, SourceContent
from app.maps.styles import MapLibreStyles, create_maplibre_styles, default_style

ROADS = SourceContent("vector", layers=("roads",))


class _Source:
    """A map source that needs no archive."""

    def __init__(self, format="pmtiles", url="file:///data/roads.pmtiles", content=ROADS):
        self.format = format
        self._url = url
        self._content = content

    def url(self):
        return self._url

    def content(self):
        return self._content


class _Unread(_Source):
    """A source whose data must not be read."""

    def content(self):
        raise AssertionError("the source was read")


HILLS = SourceContent("raster", tile_size=256)


def test_the_default_style_draws_every_layer_of_the_source():
    style = default_style(["roads", "water"], "archive")
    drawn = {(layer.get("source-layer"), layer["type"]) for layer in style["layers"]}

    assert style["layers"][0]["type"] == "background"
    assert {("roads", "line"), ("water", "fill"), ("water", "circle")} <= drawn
    assert all(layer.get("source") in (None, "archive") for layer in style["layers"])


def test_maplibre_styles_meet_the_styles_contract():
    assert isinstance(MapLibreStyles(_Source(), {}), MapStyles)


def test_a_pmtiles_source_becomes_a_maplibre_vector_source():
    style = MapLibreStyles(_Source()).style(None, transparent=False)

    assert style["sources"]["archive"] == {
        "type": "vector",
        "url": "pmtiles://file:///data/roads.pmtiles",
    }


def test_a_format_maplibre_cannot_read_is_refused_at_once():
    with pytest.raises(ValueError, match="geoparquet"):
        MapLibreStyles(_Source(format="geoparquet"))


def test_without_styles_the_default_one_is_drawn_from_the_source_layers():
    rails = SourceContent("vector", layers=("rails",))
    style = MapLibreStyles(_Source(content=rails)).style(None, transparent=False)

    assert {layer.get("source-layer") for layer in style["layers"]} == {None, "rails"}


def test_a_named_style_gets_the_source_and_keeps_its_other_sources():
    night = {
        "version": 8,
        "sources": {
            "archive": {"type": "vector", "url": "placeholder"},
            "hills": {"type": "raster"},
        },
        "layers": [
            {"id": "bg", "type": "background"},
            {"id": "r", "type": "line", "source": "archive"},
        ],
    }
    style = MapLibreStyles(_Source(), {"night": night}).style("night", transparent=False)

    assert style["sources"]["archive"]["url"].startswith("pmtiles://")
    assert style["sources"]["hills"] == {"type": "raster"}
    assert night["sources"]["archive"]["url"] == "placeholder"  # the stored style is not touched


def test_transparent_leaves_out_the_background():
    style = MapLibreStyles(_Source()).style(None, transparent=True)

    assert all(layer["type"] != "background" for layer in style["layers"])


def test_an_unknown_style_is_a_key_error():
    with pytest.raises(KeyError):
        MapLibreStyles(_Source()).style("missing", transparent=False)


def test_the_default_name_picks_a_configured_style():
    day = {"version": 8, "sources": {}, "layers": [{"id": "d", "type": "background"}]}
    styles = MapLibreStyles(_Source(), {"day": day}, default="day")

    assert styles.style(None, transparent=False)["layers"][0]["id"] == "d"
    assert styles.names() == ["day"]


def test_a_raster_pmtiles_source_becomes_a_maplibre_raster_source():
    style = MapLibreStyles(_Source(content=HILLS)).style(None, transparent=False)

    assert style["sources"]["archive"] == {
        "type": "raster",
        "url": "pmtiles://file:///data/roads.pmtiles",
        "tileSize": 256,
    }


def test_without_styles_a_raster_source_is_drawn_as_a_raster_layer():
    style = MapLibreStyles(_Source(content=HILLS)).style(None, transparent=False)

    assert [layer["type"] for layer in style["layers"]] == ["background", "raster"]
    assert style["layers"][1]["source"] == "archive"


def test_a_style_that_declares_its_source_reads_no_data():
    hills = {
        "version": 8,
        "sources": {"archive": {"type": "raster", "tileSize": 512, "maxzoom": 12}},
        "layers": [{"id": "h", "type": "raster", "source": "archive"}],
    }
    style = MapLibreStyles(_Unread(), {"hills": hills}).style("hills", transparent=False)

    assert style["sources"]["archive"] == {
        "type": "raster",
        "tileSize": 512,
        "maxzoom": 12,
        "url": "pmtiles://file:///data/roads.pmtiles",
    }


def test_tiles_maplibre_cannot_decode_are_refused_before_drawing():
    avif = SourceContent("raster", tile_size=256, encoding="avif")

    with pytest.raises(ValueError, match="AVIF"):
        MapLibreStyles(_Source(content=avif)).style(None, transparent=False)


def test_the_maplibre_factory_builds_styles_from_the_provider_options():
    night = {"version": 8, "sources": {}, "layers": [{"id": "n", "type": "background"}]}
    styles = create_maplibre_styles(
        _Source(), {"night": night}, {"default_style": "night", "style_source": "roads"}
    )

    assert isinstance(styles, MapStyles)
    assert styles.names() == ["night"]
    assert "roads" in styles.style(None, transparent=False)["sources"]


DEM = SourceContent("raster-dem", tile_size=256, encoding="png", dem="terrarium")


def test_an_elevation_source_is_shaded_by_default():
    style = MapLibreStyles(_Source(content=DEM)).style(None, transparent=False)

    assert style["sources"]["archive"] == {
        "type": "raster-dem",
        "url": "pmtiles://file:///data/roads.pmtiles",
        "tileSize": 256,
        "encoding": "terrarium",
    }
    assert [layer["type"] for layer in style["layers"]] == ["background", "hillshade"]


def test_a_style_that_declares_an_elevation_source_keeps_its_encoding():
    """Guard: a declared source is taken as written, and its data is not read."""
    declared = {
        "version": 8,
        "sources": {"archive": {"type": "raster-dem", "encoding": "mapbox"}},
        "layers": [],
    }

    style = MapLibreStyles(_Unread(content=DEM), {"relief": declared}).style(
        "relief", transparent=False
    )

    assert style["sources"]["archive"]["encoding"] == "mapbox"
