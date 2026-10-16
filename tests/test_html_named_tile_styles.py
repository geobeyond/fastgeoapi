"""The pages of a tile collection whose tile provider names several styles.

``app.*`` is imported inside ``tests.html_fixtures.native_client``, and nowhere else here.
"""

import json

import pytest

from tests.html_fixtures import config, fake_build, island_config, native_client, with_tiles


def _style(path, colour) -> str:
    path.write_text(
        json.dumps(
            {
                "version": 8,
                "sources": {"archive": {"type": "vector", "url": "pmtiles://places.pmtiles"}},
                "layers": [
                    {
                        "id": "place",
                        "type": "circle",
                        "source": "archive",
                        "source-layer": "place",
                        "paint": {"circle-color": colour},
                    }
                ],
            }
        )
    )
    return str(path)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    directory = tmp_path_factory.mktemp("named-styles")
    api_config = with_tiles(config(), directory)
    options = api_config["resources"]["places"]["providers"][0]["options"]
    options["styles"] = {
        "night": _style(directory / "night.json", "#ffffff"),
        "day": _style(directory / "day.json", "#000000"),
    }
    options["default_style"] = "day"
    return native_client(api_config, fake_build(directory / "static"))


@pytest.mark.parametrize(
    "path", ["/collections/places", "/collections/places/tiles/WebMercatorQuad"]
)
def test_the_map_offers_each_named_style_the_default_first(client, path):
    preview = island_config(client.get(path, params={"f": "html"}).text, "fga-map")

    assert [style["name"] for style in preview["styles"]] == ["day", "night"]
    assert preview["styles"][1]["style"]["layers"][0]["paint"]["circle-color"] == "#ffffff"
