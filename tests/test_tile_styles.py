"""The styles a page draws a collection's tiles with.

``app.*`` is imported at the top of this module, nowhere else.
"""

import json

import pytest
from pygeoapi.provider.base import ProviderGenericError

from app.provider.pmtiles import PMTilesProvider
from app.provider.tile_styles import DEFAULT_SOURCE, tile_source, tile_styles
from app.tiles.contract import TileContent, VectorLayer
from tests.pmtiles_fixtures import TILE_BYTES, write_archive

TILEJSON = "https://example.org/geoapi/collections/roads/tiles/WebMercatorQuad/metadata?f=tilejson"
MVT = "application/vnd.mapbox-vector-tile"


def _content(data_type="vector", **values) -> TileContent:
    defaults = {
        "data_type": data_type,
        "media_type": MVT,
        "format_parameter": "mvt",
        "min_zoom": 0,
        "max_zoom": 12,
        "bounds": (-180.0, -85.0511287, 180.0, 85.0511287),
        "center": (0.0, 0.0, 0),
        "layers": (VectorLayer("roads"), VectorLayer("water")),
    }
    return TileContent(**{**defaults, **values})


def _style(path, source="archive", colour="#000000") -> str:
    path.write_text(
        json.dumps(
            {
                "version": 8,
                "sources": {
                    source: {
                        "type": "vector",
                        "url": "pmtiles://https://bucket.example/roads.pmtiles",
                        "tiles": ["https://old.example/{z}/{x}/{y}"],
                        "attribution": "kept",
                    }
                },
                "layers": [
                    {
                        "id": "roads",
                        "type": "line",
                        "source": source,
                        "source-layer": "roads",
                        "paint": {"line-color": colour},
                    }
                ],
            }
        )
    )
    return str(path)


def _collection(*providers) -> dict:
    return {"type": "collection", "providers": list(providers)}


def _map_provider(**options) -> dict:
    return {"type": "map", "name": "app.provider.maplibre.MapLibreMapProvider", "options": options}


def _tile_provider(**options) -> dict:
    return {"type": "tile", "name": "app.provider.pmtiles.PMTilesProvider", "options": options}


def test_vector_tiles_are_read_through_the_tilejson():
    assert tile_source(TILEJSON, _content()) == {"type": "vector", "url": TILEJSON}


def test_raster_tiles_carry_their_size():
    content = _content(
        "map", media_type="image/png", format_parameter="png", layers=(), tile_size=512
    )

    assert tile_source(TILEJSON, content) == {"type": "raster", "url": TILEJSON, "tileSize": 512}


def test_elevation_tiles_carry_their_encoding():
    content = _content(
        "coverage",
        media_type="image/png",
        format_parameter="png",
        layers=(),
        tile_size=256,
        dem="terrarium",
    )

    assert tile_source(TILEJSON, content) == {
        "type": "raster-dem",
        "url": TILEJSON,
        "tileSize": 256,
        "encoding": "terrarium",
    }


def test_the_map_provider_styles_come_first_the_default_leading(tmp_path):
    styles = tile_styles(
        _collection(
            _map_provider(
                styles={
                    "night": _style(tmp_path / "night.json"),
                    "day": _style(tmp_path / "day.json", colour="#ffffff"),
                },
                default_style="day",
            ),
            _tile_provider(),
        ),
        TILEJSON,
        _content(),
    )

    assert [style.name for style in styles] == ["day", "night"]
    for style in styles:
        # The old address of the tiles goes, the other settings stay.
        assert style.document["sources"][DEFAULT_SOURCE] == {
            "type": "vector",
            "url": TILEJSON,
            "attribution": "kept",
        }


def test_the_map_provider_style_source_names_the_tiles_source(tmp_path):
    (style,) = tile_styles(
        _collection(
            _map_provider(
                styles={"night": _style(tmp_path / "night.json", source="roads-src")},
                style_source="roads-src",
            )
        ),
        TILEJSON,
        _content(),
    )

    assert style.document["sources"]["roads-src"]["url"] == TILEJSON


def test_the_tile_provider_style_is_used_without_a_map_provider(tmp_path):
    (style,) = tile_styles(
        _collection(_tile_provider(style=_style(tmp_path / "boundaries-bold.json"))),
        TILEJSON,
        _content(),
    )

    assert style.name == "boundaries-bold"
    assert style.document["sources"][DEFAULT_SOURCE]["url"] == TILEJSON


def test_the_map_provider_wins_over_the_tile_provider_style(tmp_path):
    styles = tile_styles(
        _collection(
            _map_provider(styles={"night": _style(tmp_path / "night.json")}),
            _tile_provider(style=_style(tmp_path / "boundaries-bold.json")),
        ),
        TILEJSON,
        _content(),
    )

    assert [style.name for style in styles] == ["night"]


def test_without_a_style_one_is_made_from_the_vector_layers():
    (style,) = tile_styles(_collection(_tile_provider()), TILEJSON, _content())

    layer_ids = {layer["id"] for layer in style.document["layers"]}
    assert style.name is None
    assert {"roads-line", "water-line"} <= layer_ids
    assert style.document["sources"][DEFAULT_SOURCE] == {"type": "vector", "url": TILEJSON}


@pytest.mark.parametrize(
    ("data_type", "dem", "layer_type"),
    [("map", None, "raster"), ("coverage", "mapbox", "hillshade")],
)
def test_without_a_style_raster_and_elevation_tiles_are_drawn(data_type, dem, layer_type):
    content = _content(
        data_type, media_type="image/png", format_parameter="png", layers=(), dem=dem
    )

    (style,) = tile_styles(_collection(_tile_provider()), TILEJSON, content)

    assert layer_type in {layer["type"] for layer in style.document["layers"]}


def test_a_style_that_cannot_be_read_is_left_out(tmp_path):
    styles = tile_styles(
        _collection(
            _map_provider(
                styles={
                    "missing": str(tmp_path / "missing.json"),
                    "day": _style(tmp_path / "day.json"),
                },
                default_style="missing",
            )
        ),
        TILEJSON,
        _content(),
    )

    assert [style.name for style in styles] == ["day"]


@pytest.mark.parametrize(
    "text",
    ["[]", '"a string"', '{"version": 8, "sources": [], "layers": []}'],
    ids=["a list", "a string", "sources as a list"],
)
def test_a_style_that_reads_but_is_no_style_is_left_out(tmp_path, text):
    odd = tmp_path / "odd.json"
    odd.write_text(text)

    styles = tile_styles(
        _collection(
            _map_provider(
                styles={"odd": str(odd), "day": _style(tmp_path / "day.json")},
                default_style="odd",
            )
        ),
        TILEJSON,
        _content(),
    )

    assert [style.name for style in styles] == ["day"]


def test_when_no_configured_style_can_be_read_one_is_made_from_the_tiles(tmp_path):
    (style,) = tile_styles(
        _collection(
            _map_provider(styles={"missing": str(tmp_path / "missing.json")}),
            _tile_provider(style=str(tmp_path / "also-missing.json")),
        ),
        TILEJSON,
        _content(),
    )

    assert style.name is None


def _tile_definition(path, **options) -> dict:
    return {
        "type": "tile",
        "name": "app.provider.pmtiles.PMTilesProvider",
        "data": str(path),
        "options": {"zoom": {"min": 0, "max": 2}, "schemes": ["WebMercatorQuad"], **options},
        "format": {"name": "pbf", "mimetype": MVT},
    }


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"style": 42}, "option style must be the path or URL of a MapLibre style"),
        ({"style": "  "}, "option style must be the path or URL of a MapLibre style"),
        ({"style_source": ""}, "option style_source must be the name"),
    ],
)
def test_the_tile_provider_refuses_a_style_option_it_cannot_use(tmp_path, options, message):
    archive = write_archive(tmp_path / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})

    with pytest.raises(ProviderGenericError, match=message):
        PMTilesProvider(_tile_definition(archive, **options))


def test_the_tile_provider_takes_a_style_and_its_source_name(tmp_path):
    archive = write_archive(tmp_path / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})

    provider = PMTilesProvider(
        _tile_definition(archive, style="styles/roads.json", style_source="roads")
    )

    assert provider.options["style"] == "styles/roads.json"
