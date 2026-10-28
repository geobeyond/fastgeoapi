"""The ingest command, as both front-ends run it."""

from __future__ import annotations

import json
from importlib.metadata import EntryPoint

import pytest
from click.testing import CliRunner
from pmtiles.tile import Compression, TileType, zxy_to_tileid
from pmtiles.writer import Writer
from ruamel.yaml import YAML

import fastgeoapi_portolan.tiles as tiles_module
from fastgeoapi_portolan import command
from fastgeoapi_portolan.catalog.walk import NO_PORTOLAN_SCHEMA
from fastgeoapi_portolan.command import find_validator, ingest_command

PARQUET = "application/vnd.apache.parquet"
COG = "image/tiff; application=geotiff; profile=cloud-optimized"
CONFIG = """\
server:
  url: ${PYGEOAPI_BASEURL}
resources:
  lakes:
    type: collection
    title: Lakes
"""


def _run(*arguments, validator=None):
    return CliRunner().invoke(ingest_command(validator=lambda: validator), list(arguments))


def _collection(identifier, **fields):
    """A plain STAC collection with GeoParquet data whose columns the catalog names."""
    document = {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": [],
        "id": identifier,
        "title": identifier.capitalize(),
        "description": f"The {identifier} collection.",
        "license": "CC-BY-4.0",
        "extent": {
            "spatial": {"bbox": [[12.3, 41.8, 12.6, 42.0]]},
            "temporal": {"interval": [["2026-01-01T00:00:00Z", None]]},
        },
        "table:columns": [{"name": "id"}, {"name": "geometry"}],
        "assets": {"data": {"href": f"./{identifier}.parquet", "type": PARQUET, "roles": ["data"]}},
    }
    document.update(fields)
    return document


def _raster(identifier):
    return _collection(
        identifier, assets={"data": {"href": "./dem.tif", "type": COG, "roles": ["data"]}}
    )


def _write_catalog(folder, *collections):
    """A catalog in ``folder`` linking each collection from a folder named after it."""
    folder.mkdir(parents=True, exist_ok=True)
    links = [{"rel": "root", "href": "./catalog.json", "type": "application/json"}]
    for document in collections:
        path = folder / document["id"] / "collection.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        structural = [
            {"rel": "root", "href": "../catalog.json", "type": "application/json"},
            {"rel": "parent", "href": "../catalog.json", "type": "application/json"},
        ]
        path.write_text(json.dumps({**document, "links": structural}))
        links.append(
            {
                "rel": "child",
                "href": f"./{document['id']}/collection.json",
                "type": "application/json",
            }
        )
    catalog = {
        "type": "Catalog",
        "stac_version": "1.1.0",
        "id": "example",
        "description": "An example catalog.",
        "links": links,
    }
    (folder / "catalog.json").write_text(json.dumps(catalog))
    return folder / "catalog.json"


@pytest.fixture
def base(tmp_path):
    return tmp_path.resolve()


@pytest.fixture
def config(base):
    path = base / "pygeoapi-config.yml"
    path.write_text(CONFIG)
    return path


def _resources(text):
    return YAML(typ="safe").load(text)["resources"]


def test_without_into_the_yaml_goes_to_stdout_and_the_summary_to_stderr(base):
    root = _write_catalog(base / "cat", _collection("roads"), _raster("dem"))

    result = _run("--from-portolan", str(root))

    assert result.exit_code == 0, result.output
    assert list(_resources(result.stdout)) == ["roads"]
    assert "roads" in result.stderr
    assert "dem: format not handled yet" in result.stderr
    assert NO_PORTOLAN_SCHEMA in result.stderr
    assert "resources:" not in result.stderr


def test_json_summary_lists_every_outcome(base, config):
    folder = base / "cat"
    root = _write_catalog(folder, _collection("roads"), _collection("parks"))
    assert _run("--from-portolan", str(root), "--into", str(config)).exit_code == 0
    undescribed = _collection("undescribed")
    del undescribed["description"]
    _write_catalog(
        folder,
        _collection("roads", title="Main roads"),
        _collection("rivers"),
        _raster("dem"),
        undescribed,
    )

    result = _run("--from-portolan", str(root), "--into", str(config), "--json")

    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert set(summary) == {
        "catalog",
        "into",
        "added",
        "updated",
        "skipped",
        "missing",
        "pruned",
        "choices",
        "warnings",
    }
    assert (summary["catalog"], summary["into"]) == (str(root), str(config))
    assert (summary["added"], summary["updated"]) == (["rivers"], ["roads"])
    assert [entry["collection"] for entry in summary["skipped"]] == ["undescribed", "dem"]
    assert summary["skipped"][0]["reason"].startswith("does not conform to ")
    assert summary["skipped"][1]["reason"].startswith("format not handled yet: ")
    assert (summary["missing"], summary["pruned"]) == (["parks"], [])
    assert summary["choices"]["roads"] == [
        "data: collection asset",
        "id_field: id (column name)",
        "geometry_column: geometry (column name)",
    ]
    assert set(summary["choices"]) == {"roads", "rivers"}
    assert NO_PORTOLAN_SCHEMA in summary["warnings"]


def test_into_writes_the_document_and_reports_on_stdout(base, config):
    root = _write_catalog(base / "cat", _collection("roads"))

    result = _run("--from-portolan", str(root), "--into", str(config), validator=lambda _: [])

    assert result.exit_code == 0, result.output
    text = config.read_text()
    assert text.startswith(CONFIG)
    assert _resources(text)["roads"]["ingest"]["collection"] == "roads"
    assert "added:" in result.stdout
    assert "roads" in result.stdout
    assert "providers:" not in result.stdout
    assert result.stderr == ""


def test_a_failing_validator_refuses_before_writing(base, config):
    root = _write_catalog(base / "cat", _collection("roads"))

    result = _run(
        "--from-portolan",
        str(root),
        "--into",
        str(config),
        validator=lambda _: ["resources.roads.providers: not a provider"],
    )

    assert result.exit_code == 1
    assert config.read_text() == CONFIG
    assert "resources.roads.providers: not a provider" in result.stderr


def test_the_validator_reads_the_merged_document(base, config):
    root = _write_catalog(base / "cat", _collection("roads"))
    seen = []

    def validator(text):
        seen.append(text)
        return []

    _run("--from-portolan", str(root), "--into", str(config), validator=validator)

    assert seen == [config.read_text()]


def test_the_validator_is_looked_up_only_when_the_command_runs(base, config):
    root = _write_catalog(base / "cat", _collection("roads"))
    lookups = []

    def factory():
        lookups.append(True)

    ingest = ingest_command(validator=factory)
    assert lookups == []

    CliRunner().invoke(ingest, ["--from-portolan", str(root), "--into", str(config)])

    assert lookups == [True]


def test_without_a_validator_the_summary_says_the_document_was_not_validated(base, config):
    root = _write_catalog(base / "cat", _collection("roads"))

    result = _run("--from-portolan", str(root), "--into", str(config))

    assert result.exit_code == 0, result.output
    assert "roads" in _resources(config.read_text())
    assert "not validated" in result.stdout


def test_strict_turns_a_skipped_collection_into_an_error(base, config):
    root = _write_catalog(base / "cat", _collection("roads"), _raster("dem"))

    printed = _run("--from-portolan", str(root), "--strict")
    merged = _run("--from-portolan", str(root), "--into", str(config), "--strict")

    assert printed.exit_code == 1
    assert printed.stdout == ""
    assert "dem: format not handled yet" in printed.stderr
    assert merged.exit_code == 1
    assert config.read_text() == CONFIG


def test_strict_turns_a_nonconforming_collection_into_an_error(base):
    undescribed = _collection("undescribed")
    del undescribed["description"]
    root = _write_catalog(base / "cat", _collection("roads"), undescribed)

    strict = _run("--from-portolan", str(root), "--strict")
    lenient = _run("--from-portolan", str(root))

    assert strict.exit_code == 1
    assert lenient.exit_code == 0
    assert "undescribed: does not conform to " in lenient.stderr


def test_an_unreadable_root_exits_1_and_writes_nothing(base, config):
    result = _run("--from-portolan", str(base / "nowhere" / "catalog.json"), "--into", str(config))

    assert result.exit_code == 1
    assert config.read_text() == CONFIG
    assert "could not be read" in result.stderr


def test_a_concurrent_edit_exits_1(base, config):
    root = _write_catalog(base / "cat", _collection("roads"))

    def editing(_):
        # Someone saves the document while the ingest is about to write it.
        config.write_text(CONFIG + "# edited\n")
        return []

    result = _run("--from-portolan", str(root), "--into", str(config), validator=editing)

    assert result.exit_code == 1
    assert config.read_text() == CONFIG + "# edited\n"
    assert "changed since it was read" in result.stderr


def test_two_collections_with_one_id_exit_1(base):
    root = _write_catalog(base / "cat", _collection("roads"))
    twin = base / "cat" / "twin" / "collection.json"
    twin.parent.mkdir()
    twin.write_text((base / "cat" / "roads" / "collection.json").read_text())
    catalog = json.loads(root.read_text())
    catalog["links"].append(
        {"rel": "child", "href": "./twin/collection.json", "type": "application/json"}
    )
    root.write_text(json.dumps(catalog))

    result = _run("--from-portolan", str(root))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "would both be the resource roads" in result.stderr


def test_a_document_that_is_not_yaml_exits_1(base):
    root = _write_catalog(base / "cat", _collection("roads"))
    config = base / "broken.yml"
    config.write_text("resources: [\n")

    result = _run("--from-portolan", str(root), "--into", str(config))

    assert result.exit_code == 1
    assert config.read_text() == "resources: [\n"
    assert str(config) in result.stderr


def test_an_ingest_that_changes_nothing_does_not_write(base, config):
    root = _write_catalog(base / "cat", _collection("roads"))
    _run("--from-portolan", str(root), "--into", str(config))
    written = config.stat().st_mtime_ns
    lookups = []

    def factory():
        lookups.append(True)

    ingest = ingest_command(validator=factory)
    result = CliRunner().invoke(ingest, ["--from-portolan", str(root), "--into", str(config)])

    assert result.exit_code == 0, result.output
    assert config.stat().st_mtime_ns == written
    assert lookups == []


def test_prune_removes_what_the_catalog_dropped(base, config):
    folder = base / "cat"
    root = _write_catalog(folder, _collection("roads"), _collection("parks"))
    _run("--from-portolan", str(root), "--into", str(config))
    _write_catalog(folder, _collection("roads"))

    result = _run("--from-portolan", str(root), "--into", str(config), "--prune", "--json")

    assert json.loads(result.stdout)["pruned"] == ["parks"]
    assert list(_resources(config.read_text())) == ["lakes", "roads"]


def test_prune_waits_for_a_walk_that_read_every_document(base, config):
    folder = base / "cat"
    root = _write_catalog(folder, _collection("roads"), _collection("parks"))
    _run("--from-portolan", str(root), "--into", str(config))
    (folder / "parks" / "collection.json").unlink()

    result = _run("--from-portolan", str(root), "--into", str(config), "--prune", "--json")

    summary = json.loads(result.stdout)
    assert (summary["missing"], summary["pruned"]) == (["parks"], [])
    assert "parks" in _resources(config.read_text())
    assert any(warning.startswith("nothing pruned: ") for warning in summary["warnings"])


def test_prune_waits_for_a_walk_within_its_limit(base, config):
    folder = base / "cat"
    root = _write_catalog(folder, _collection("roads"), _collection("parks"))
    _run("--from-portolan", str(root), "--into", str(config))

    result = _run(
        "--from-portolan",
        str(root),
        "--into",
        str(config),
        "--prune",
        "--max-documents",
        "2",
        "--json",
    )

    summary = json.loads(result.stdout)
    assert summary["pruned"] == []
    assert "parks" in _resources(config.read_text())
    assert any(warning.startswith("nothing pruned: ") for warning in summary["warnings"])


def test_selection_prefix_and_columns_reach_the_resources(base):
    roads = _collection(
        "roads", **{"table:columns": [{"name": "road_code"}, {"name": "footprint"}]}
    )
    root = _write_catalog(base / "cat", roads, _collection("parks"))

    result = _run(
        "--from-portolan",
        str(root),
        "--collection",
        "roads",
        "--prefix",
        "rome-",
        "--id-field",
        "roads=road_code",
        "--geometry-column",
        "roads=footprint",
    )

    assert result.exit_code == 0, result.output
    resources = _resources(result.stdout)
    assert list(resources) == ["rome-roads"]
    (provider,) = resources["rome-roads"]["providers"]
    assert (provider["id_field"], provider["geometry_column"]) == ("road_code", "footprint")


def test_store_options_keep_their_booleans(base):
    root = _write_catalog(base / "cat", _collection("roads"))

    result = _run(
        "--from-portolan",
        str(root),
        "--store-option",
        "region=us-west-2",
        "--store-option",
        "skip_signature=true",
    )

    assert result.exit_code == 0, result.output
    (provider,) = _resources(result.stdout)["roads"]["providers"]
    assert provider["store_options"] == {"region": "us-west-2", "skip_signature": True}


def test_a_pair_without_an_equals_sign_is_a_usage_error(base):
    root = _write_catalog(base / "cat", _collection("roads"))

    result = _run("--from-portolan", str(root), "--id-field", "roads")

    assert result.exit_code == 2
    assert "collection=column" in result.stderr


def test_max_documents_bounds_the_walk(base):
    root = _write_catalog(base / "cat", _collection("roads"), _collection("parks"))

    result = _run("--from-portolan", str(root), "--max-documents", "2", "--json")

    summary = json.loads(result.stderr)
    assert result.exit_code == 0, result.output
    assert summary["added"] == ["roads"]
    assert any("its limit of 2 documents" in warning for warning in summary["warnings"])


def test_max_document_bytes_bounds_each_document(base):
    root = _write_catalog(base / "cat", _collection("roads"))

    result = _run("--from-portolan", str(root), "--max-document-bytes", "100")

    assert result.exit_code == 1
    assert "larger than 100 bytes" in result.stderr


def _write_archive(path):
    header = {
        "tile_type": TileType.MVT,
        "tile_compression": Compression.NONE,
        "min_lon_e7": 123000000,
        "min_lat_e7": 418000000,
        "max_lon_e7": 126000000,
        "max_lat_e7": 420000000,
        "center_zoom": 0,
        "center_lon_e7": 124500000,
        "center_lat_e7": 419000000,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        writer = Writer(handle)
        writer.write_tile(zxy_to_tileid(0, 0, 0), b"tile")
        writer.finalize(header, {"vector_layers": [{"id": "roads", "minzoom": 0, "maxzoom": 0}]})


def test_a_provider_that_does_not_answer_is_kept_by_a_second_ingest(base, config, monkeypatch):
    assets = {
        "data": {"href": "./roads.parquet", "type": PARQUET, "roles": ["data"]},
        "tiles": {
            "href": "./roads.pmtiles",
            "type": "application/vnd.pmtiles",
            "roles": ["visual"],
        },
    }
    root = _write_catalog(base / "cat", _collection("roads", assets=assets))
    _write_archive(base / "cat" / "roads" / "roads.pmtiles")
    first = _run("--from-portolan", str(root), "--into", str(config))
    written = config.read_text()

    async def unavailable(*args, **kwargs):
        raise OSError("HTTP 503 Service Unavailable")

    monkeypatch.setattr(tiles_module, "read_range", unavailable)
    second = _run("--from-portolan", str(root), "--into", str(config))

    assert first.exit_code == 0, first.output
    assert [p["type"] for p in _resources(written)["roads"]["providers"]] == ["feature", "tile"]
    assert second.exit_code == 0, second.output
    assert config.read_text() == written
    assert "roads: pmtiles: the archive could not be read: HTTP 503" in second.stdout


def test_the_validator_is_discovered_from_the_entry_points(monkeypatch):
    entry_point = EntryPoint(
        name="fastgeoapi", value="json:dumps", group="fastgeoapi_portolan.validators"
    )
    groups = []

    def entry_points(*, group):
        groups.append(group)
        return [entry_point]

    monkeypatch.setattr(command, "entry_points", entry_points)

    assert find_validator() is json.dumps
    assert groups == ["fastgeoapi_portolan.validators"]


def test_without_an_entry_point_there_is_no_validator(monkeypatch):
    monkeypatch.setattr(command, "entry_points", lambda *, group: [])

    assert find_validator() is None


def test_prune_keeps_a_collection_the_catalog_still_lists(base, config):
    folder = base / "cat"
    root = _write_catalog(folder, _collection("roads"), _collection("parks"))
    _run("--from-portolan", str(root), "--into", str(config))
    _write_catalog(folder, _collection("roads"), _raster("parks"))

    result = _run("--from-portolan", str(root), "--into", str(config), "--prune", "--json")

    summary = json.loads(result.stdout)
    assert (summary["missing"], summary["pruned"]) == ([], [])
    assert "parks" in _resources(config.read_text())


def test_a_resource_written_by_hand_is_reported_and_kept(base, config):
    root = _write_catalog(base / "cat", _collection("lakes"))

    result = _run("--from-portolan", str(root), "--into", str(config), "--json")

    summary = json.loads(result.stdout)
    assert result.exit_code == 0, result.output
    assert config.read_text() == CONFIG
    assert summary["skipped"] == [
        {
            "collection": "lakes",
            "reason": "the configuration has a resource lakes written by hand: left alone",
        }
    ]
    assert summary["choices"] == {}


def test_strict_counts_a_resource_left_alone(base, config):
    root = _write_catalog(base / "cat", _collection("lakes"), _collection("roads"))

    result = _run("--from-portolan", str(root), "--into", str(config), "--strict")

    assert result.exit_code == 1
    assert config.read_text() == CONFIG
