"""The parameters the document publishes for a native map, exactly those the route applies.

``app.*`` is imported inside the tests, nowhere else.
"""

import pytest

from tests.maps_fixtures import map_provider
from tests.pmtiles_fixtures import TILE_BYTES, write_archive
from tests.test_tiles_async_route import _collection, _config

CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
WEB_MERCATOR = "http://www.opengis.net/def/crs/EPSG/0/3857"
MAP = "/collections/roads/map"
STYLED = "/collections/roads/styles/{styleId}/map"
PATHS = (MAP, STYLED)


def _roads(folder, **extents) -> dict:
    archive = write_archive(folder / "roads.pmtiles", {(0, 0, 0): TILE_BYTES(0, 0, 0)})
    style = folder / "night.json"
    style.write_text('{"version": 8, "sources": {}, "layers": []}')
    collection = _collection("Roads", [map_provider(archive, styles={"night": str(style)})])
    collection["extents"].update(extents)
    return _config({"roads": collection})


def _document(folder, **extents) -> dict:
    from app.pygeoapi.factory import build_openapi

    return build_openapi(_roads(folder, **extents))


def _parameters(document: dict, path: str) -> dict[str, dict]:
    """The parameters of a path by name; an external reference is keyed by its own text."""
    components = document["components"]["parameters"]
    found = {}
    for parameter in document["paths"][path]["get"]["parameters"]:
        ref = parameter.get("$ref")
        if ref is None:
            found[parameter["name"]] = parameter
        elif ref.startswith("#/components/parameters/"):
            found[components[ref.rsplit("/", 1)[1]]["name"]] = {"$ref": ref}
        else:
            found[ref] = parameter
    return found


@pytest.fixture(scope="module")
def document(tmp_path_factory):
    return _document(tmp_path_factory.mktemp("published"))


@pytest.mark.parametrize("path", PATHS)
def test_the_bbox_is_published_with_four_numbers(document, path):
    schema = _parameters(document, path)["bbox"]["schema"]

    assert (schema["minItems"], schema["maxItems"]) == (4, 4)
    # The features keep the shared definition, with its six numbers.
    assert document["components"]["parameters"]["bbox"]["schema"]["maxItems"] == 6


@pytest.mark.parametrize("path", PATHS)
def test_bbox_crs_is_published_as_uris(document, path):
    parameters = _parameters(document, path)

    assert parameters["bbox-crs"]["schema"] == {
        "type": "string",
        "format": "uri",
        "enum": [CRS84, WEB_MERCATOR],
        "default": CRS84,
    }
    refs = [p.get("$ref", "") for p in document["paths"][path]["get"]["parameters"]]
    assert not any(ref.endswith("/bbox-crs-epsg") for ref in refs)


@pytest.mark.parametrize("path", PATHS)
def test_crs_is_published_with_the_crs_the_provider_draws(document, path):
    schema = _parameters(document, path)["crs"]["schema"]

    assert (schema["enum"], schema["default"]) == ([WEB_MERCATOR], WEB_MERCATOR)


@pytest.mark.parametrize("path", PATHS)
def test_f_is_published_with_the_provider_formats(document, path):
    assert _parameters(document, path)["f"]["schema"]["enum"] == ["png"]


@pytest.mark.parametrize("path", PATHS)
def test_datetime_is_published_only_with_a_temporal_extent(document, tmp_path, path):
    timed = _document(tmp_path, temporal={"begin": "2020-01-01T00:00:00Z", "end": None})

    assert "datetime" not in _parameters(document, path)
    assert _parameters(timed, path)["datetime"]["schema"]["type"] == "string"


@pytest.mark.parametrize("path", PATHS)
def test_subset_is_published_only_with_additional_dimensions(document, tmp_path, path):
    deep = _document(
        tmp_path,
        elevation={"range": [0, 100], "url": "https://example.org/elevation", "units": "m"},
    )

    def subsets(doc):
        return [name for name in _parameters(doc, path) if name.endswith("/parameters/subset")]

    assert subsets(document) == []
    assert len(subsets(deep)) == 1


def test_a_collection_that_is_not_native_keeps_pygeoapis_parameters():
    from app.pygeoapi.factory import build_openapi

    sync = {
        "type": "map",
        "name": "tests.test_maps_async_route.SyncMaps",
        "data": "unused",
        "storage_crs": WEB_MERCATOR,
        "format": {"name": "png", "mimetype": "image/png"},
    }
    document = build_openapi(_config({"lakes": _collection("Lakes", [sync])}))
    refs = [
        p.get("$ref", "") for p in document["paths"]["/collections/lakes/map"]["get"]["parameters"]
    ]

    assert "#/components/parameters/bbox-crs-epsg" in refs


def test_the_default_crs_is_the_storage_crs_or_the_first_one():
    from app.interfaces.providers import MapCapabilities
    from app.pygeoapi.map_limits import default_map_crs

    capabilities = MapCapabilities(crs=(WEB_MERCATOR, CRS84), formats=("png",))

    assert default_map_crs({"storage_crs": CRS84}, capabilities) == CRS84
    assert default_map_crs({"storage_crs": CRS84.lower()}, capabilities) == CRS84
    assert default_map_crs({}, capabilities) == WEB_MERCATOR
    assert default_map_crs({"storage_crs": "EPSG:32633"}, capabilities) == WEB_MERCATOR
