"""``fastgeoapi config ingest``: the ingest command of fastgeoapi-portolan, run from fastgeoapi.

``app.*`` is imported inside the tests, and nowhere else here.
"""

import json
import shutil
import sys
from pathlib import Path

import typer
from pygeoapi.util import yaml_load
from typer.testing import CliRunner

from tests.html_fixtures import SERVER_URL, fake_build, island_config, native_client
from tests.pmtiles_fixtures import TILE_BYTES, write_archive

CONFIG = Path("tests/data/pygeoapi-config.yml")
PARQUET = "application/vnd.apache.parquet"
PMTILES = "application/vnd.pmtiles"
NEEDS_EXTRA = (
    'fastgeoapi config ingest needs the portolan extra: pip install "fastgeoapi[portolan]"'
)


def _collection(identifier, assets, **fields):
    return {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": [],
        "id": identifier,
        "title": identifier.capitalize(),
        "description": f"The {identifier} collection.",
        "license": "CC0-1.0",
        "extent": {
            "spatial": {"bbox": [[-180, -90, 180, 90]]},
            "temporal": {"interval": [["2026-01-01T00:00:00Z", None]]},
        },
        "links": [
            {"rel": "root", "href": "../catalog.json", "type": "application/json"},
            {"rel": "parent", "href": "../catalog.json", "type": "application/json"},
        ],
        "assets": assets,
        **fields,
    }


def _style(path, colour):
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


def _catalog(folder):
    """A STAC catalog with GeoParquet reservoirs and PMTiles places with two styles."""
    reservoirs = folder / "reservoirs"
    reservoirs.mkdir(parents=True)
    shutil.copy("tests/data/lakes.parquet", reservoirs / "reservoirs.parquet")
    data = {"href": "./reservoirs.parquet", "type": PARQUET, "roles": ["data"]}
    (reservoirs / "collection.json").write_text(
        json.dumps(
            _collection(
                "reservoirs",
                {"data": data},
                **{"table:columns": [{"name": "id"}, {"name": "geometry"}]},
            )
        )
    )

    places = folder / "places"
    places.mkdir()
    write_archive(
        places / "places.pmtiles",
        {(0, 0, 0): TILE_BYTES(0, 0, 0)},
        metadata={"name": "Places", "vector_layers": [{"id": "place", "minzoom": 0, "maxzoom": 2}]},
    )
    _style(places / "day.json", "#000000")
    _style(places / "night.json", "#ffffff")
    style = {"type": "application/json"}
    assets = {
        "tiles": {"href": "./places.pmtiles", "type": PMTILES, "roles": ["visual"]},
        "day": {**style, "href": "./day.json", "roles": ["style", "default"], "title": "day"},
        "night": {**style, "href": "./night.json", "roles": ["style"], "title": "night"},
    }
    (places / "collection.json").write_text(json.dumps(_collection("places", assets)))

    child = {"rel": "child", "type": "application/json"}
    catalog = {
        "type": "Catalog",
        "stac_version": "1.1.0",
        "id": "example",
        "description": "An example catalog.",
        "links": [
            {"rel": "root", "href": "./catalog.json", "type": "application/json"},
            {**child, "href": "./reservoirs/collection.json"},
            {**child, "href": "./places/collection.json"},
        ],
    }
    (folder / "catalog.json").write_text(json.dumps(catalog))
    return folder / "catalog.json"


def _ingest(*arguments):
    from app.cli import app

    return CliRunner().invoke(app, ["config", "ingest", *arguments])


def test_config_ingest_writes_resources_the_app_serves(tmp_path):
    root = _catalog(tmp_path / "catalog")
    into = tmp_path / "pygeoapi-config.yml"
    shutil.copy(CONFIG, into)

    result = _ingest("--from-portolan", str(root), "--into", str(into))

    assert result.exit_code == 0, result.output
    with into.open() as handle:
        api_config = yaml_load(handle)
    assert list(api_config["resources"]) == ["obs", "lakes", "hello-world", "reservoirs", "places"]
    api_config["server"]["url"] = SERVER_URL
    client = native_client(api_config, fake_build(tmp_path / "static"))
    items = client.get("/collections/reservoirs/items", params={"f": "json"})
    tileset = client.get("/collections/places/tiles/WebMercatorQuad", params={"f": "html"})
    assert items.status_code == 200, items.text
    assert items.json()["numberReturned"] == 4
    preview = island_config(tileset.text, "fga-map")
    assert [style["name"] for style in preview["styles"]] == ["day", "night"]


def test_a_document_with_an_unset_variable_is_not_written(tmp_path, monkeypatch):
    monkeypatch.delenv("FASTGEOAPI_TEST_UNSET", raising=False)
    root = _catalog(tmp_path / "catalog")
    into = tmp_path / "pygeoapi-config.yml"
    text = CONFIG.read_text().replace("${FASTGEOAPI_CONTEXT}", "${FASTGEOAPI_TEST_UNSET}")
    into.write_text(text)

    result = _ingest("--from-portolan", str(root), "--into", str(into))

    assert result.exit_code == 1
    assert into.read_text() == text
    assert "${FASTGEOAPI_TEST_UNSET} has no value in this environment" in result.stderr


def test_config_ingest_shows_the_help_of_the_command():
    result = _ingest("--help")

    assert result.exit_code == 0, result.output
    assert "Usage: fastgeoapi config ingest [OPTIONS]" in result.stdout
    assert "--from-portolan" in result.stdout


def test_a_usage_error_exits_2():
    result = _ingest("--prune")

    assert result.exit_code == 2
    assert "--from-portolan" in result.stderr


def test_without_the_package_the_command_names_the_extra(monkeypatch):
    from app.cli import add_config_ingest

    # A module already imported is found in sys.modules before its package.
    for name in ("fastgeoapi_portolan", "fastgeoapi_portolan.command"):
        monkeypatch.setitem(sys.modules, name, None)
    root = typer.Typer()
    config = typer.Typer()
    root.add_typer(config, name="config")
    add_config_ingest(config)

    result = CliRunner().invoke(root, ["config", "ingest", "--from-portolan", "catalog.json"])

    assert result.exit_code == 1
    assert NEEDS_EXTRA in result.stderr


def test_the_plugin_finds_the_editor_validator():
    from fastgeoapi_portolan.command import find_validator

    from app.editor.inspect import validation_problems

    assert find_validator() is validation_problems
