"""The map paths in the document: unique operation ids, an image response, the styled path."""

import pytest

from tests.maps_fixtures import map_provider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config


@pytest.fixture(scope="module")
def document(tmp_path_factory):
    from app.pygeoapi.factory import build_openapi

    folder = tmp_path_factory.mktemp("openapi-maps")
    archive = write_archive(folder / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})
    style = folder / "night.json"
    style.write_text('{"version": 8, "sources": {}, "layers": []}')
    return build_openapi(
        _config(
            {
                "roads": _collection(
                    "Roads", [map_provider(archive, styles={"night": str(style)})]
                ),
                "rails": _collection("Rails", [map_provider(archive)]),
            }
        )
    )


def test_every_map_operation_has_its_own_id(document):
    assert document["paths"]["/collections/roads/map"]["get"]["operationId"] == "getRoadsMap"
    assert document["paths"]["/collections/rails/map"]["get"]["operationId"] == "getRailsMap"


def test_the_map_answers_an_image(document):
    content = document["paths"]["/collections/roads/map"]["get"]["responses"]["200"]["content"]

    assert list(content) == ["image/png"]


def test_a_collection_with_styles_describes_the_styled_map(document):
    styled = document["paths"]["/collections/roads/styles/{styleId}/map"]["get"]
    (style_id,) = [p for p in styled["parameters"] if p.get("name") == "styleId"]

    assert styled["operationId"] == "getRoadsStyledMap"
    assert style_id["in"] == "path"
    assert style_id["schema"]["enum"] == ["night"]


def test_a_collection_without_styles_has_no_styled_path(document):
    assert "/collections/rails/styles/{styleId}/map" not in document["paths"]
