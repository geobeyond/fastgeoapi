"""The martin config the tile provider asks for (app/provider/martin.py).

Pure translation from a tile provider's definition to a martin config:
no `martin_py` involved, so these run whether or not the
`martin_wrapper` extra is installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pygeoapi.provider.base import ProviderGenericError

from app.provider.martin import (
    MartinTilesConfig,
    layer_id_from_data,
    martin_config_for_source,
    martin_config_from_pygeoapi,
    names_one_object,
    source_kind,
)
from app.tiles.sources import TileSourceContext

MVT = "application/vnd.mapbox-vector-tile"


def _unused(*args, **kwargs):
    raise AssertionError("translating the config reads no data")


def _martin_config(data: str, store_options: dict | None = None, **options) -> dict:
    """The martin config of a tile provider serving ``data`` with ``options``."""
    context = TileSourceContext(
        data=data,
        options={"zoom": {"min": 0, "max": 14}, **options},
        media_type=MVT,
        dem=None,
        ranges=_unused,
        cached=_unused,
        offload=_unused,
        store_options=store_options,
    )
    return MartinTilesConfig.from_context(context).martin_config()


# --- one provider, one source ----------------------------------------------


def test_a_geojson_file_becomes_a_geojson_source_named_after_it():
    assert _martin_config("tests/data/lakes.geojson") == {
        "geojson": {"sources": {"lakes": "tests/data/lakes.geojson"}}
    }


def test_a_geoparquet_file_becomes_a_duckdb_source():
    assert _martin_config(
        "tests/data/parcels.parquet", geometry_column="wkb_geometry", srid=3857
    ) == {
        "duckdb": {
            "sources": [
                {
                    "geoparquet": "tests/data/parcels.parquet",
                    "layer_id": "parcels",
                    "geometry_column": "wkb_geometry",
                    "srid": 3857,
                }
            ]
        }
    }


def test_geometry_column_and_srid_default_as_in_the_geoparquet_provider():
    (source,) = _martin_config("tests/data/parcels.parquet")["duckdb"]["sources"]
    assert (source["geometry_column"], source["srid"]) == ("geom", 4326)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("s3://bucket/theme=places/", "s3://bucket/theme=places/**/*.parquet"),
        ("s3://bucket/theme=places", "s3://bucket/theme=places/**/*.parquet"),
        ("s3://bucket/places.parquet", "s3://bucket/places.parquet"),
        ("s3://bucket/part-*.parquet", "s3://bucket/part-*.parquet"),
    ],
)
def test_a_remote_geoparquet_directory_becomes_a_glob(data, expected):
    (source,) = _martin_config(data)["duckdb"]["sources"]
    assert source["geoparquet"] == expected


def test_a_location_naming_no_file_takes_the_default_layer_id():
    (source,) = _martin_config("s3://bucket/theme=places/")["duckdb"]["sources"]
    assert source["layer_id"] == "tiles"


def test_layer_id_option_names_the_source():
    assert _martin_config("tests/data/lakes.geojson", layer_id="water") == {
        "geojson": {"sources": {"water": "tests/data/lakes.geojson"}}
    }


def test_a_pmtiles_archive_becomes_a_pmtiles_source():
    assert _martin_config("tests/data/basemap.pmtiles") == {
        "pmtiles": {"sources": {"basemap": "tests/data/basemap.pmtiles"}}
    }


def test_cache_size_sets_martins_tile_cache():
    assert _martin_config("tests/data/lakes.geojson", cache_size_mb=0)["cache"] == {"size_mb": 0}


def test_store_options_are_translated_for_a_remote_dataset():
    (source,) = _martin_config(
        "s3://bucket/places.parquet",
        store_options={
            "key_id": "k",
            "secret": "s",
            "scope": "s3://bucket",
            "endpoint": "minio:9000",
            "use_ssl": False,
        },
    )["duckdb"]["sources"]
    assert source["access_key_id"] == "k"
    assert source["secret_access_key"] == "s"
    assert source["endpoint"] == "http://minio:9000"
    assert source["allow_http"] is True
    assert "scope" not in source


def test_store_options_are_ignored_for_a_local_file():
    (source,) = _martin_config("tests/data/parcels.parquet", store_options={"key_id": "k"})[
        "duckdb"
    ]["sources"]
    assert "access_key_id" not in source


@pytest.mark.parametrize(
    ("data", "options"),
    [
        ("tests/data/obs.csv", {}),
        ("tests/data/parcels", {}),
        ("tests/data/lakes.geojson", {"worker_threads": 0}),
        ("tests/data/lakes.geojson", {"cache_size_mb": -1}),
        ("tests/data/lakes.geojson", {"srid": "not-a-number"}),
        ("tests/data/lakes.geojson", {"layer_id": " "}),
    ],
)
def test_what_martin_cannot_serve_is_refused(data, options):
    with pytest.raises(ProviderGenericError):
        _martin_config(data, **options)


def test_credentials_stay_out_of_the_configs_repr():
    context = TileSourceContext(
        data="s3://bucket/places.parquet",
        options={},
        media_type=MVT,
        dem=None,
        ranges=_unused,
        cached=_unused,
        offload=_unused,
        store_options={"secret": "do-not-print"},
    )
    assert "do-not-print" not in repr(MartinTilesConfig.from_context(context))


# --- the building blocks ------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "kind"),
    [
        ("data/rome.geojson", "geojson"),
        ("https://example.org/a.json", "geojson"),
        ("s3://b/tiles/roads.pmtiles", "pmtiles"),
        ("s3://b/overture/roads.parquet", "duckdb"),
        ("data/roads.geoparquet", "duckdb"),
        ("s3://b/overture/*.parquet", "duckdb"),
        ("s3://b/overture/", "duckdb"),
        ("s3://b/theme=places", "duckdb"),
        ("data/obs.csv", None),
        ("data/folder", None),
    ],
)
def test_source_kind_by_extension(data, kind):
    assert source_kind(data) == kind


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("s3://b/overture/transportation-lazio.parquet", "transportation-lazio"),
        ("data/rome.geojson", "rome"),
        ("s3://b/overture/*.parquet", "fallback"),
        ("s3://b/overture/", "fallback"),
        ("data/folder", "fallback"),
    ],
)
def test_layer_id_from_data(data, expected):
    assert layer_id_from_data(data, "fallback") == expected


@pytest.mark.parametrize(
    ("data", "one"),
    [
        ("s3://b/a.parquet", True),
        ("data/rome.geojson", True),
        ("s3://b/*.parquet", False),
        ("s3://b/prefix/", False),
        ("s3://b/theme=places", False),
    ],
)
def test_only_a_single_object_has_a_version_to_follow(data, one):
    assert names_one_object(data) is one


def test_one_source_config_per_kind():
    assert martin_config_for_source("geojson", "a.geojson", "a") == {
        "geojson": {"sources": {"a": "a.geojson"}}
    }
    assert martin_config_for_source("pmtiles", "a.pmtiles", "a", cache_size_mb=0) == {
        "pmtiles": {"sources": {"a": "a.pmtiles"}},
        "cache": {"size_mb": 0},
    }


# --- a whole pygeoapi config (kept for the benchmark) ---------------------------


def test_a_pygeoapi_config_keeps_only_what_martin_can_serve():
    """The repo fixture (GeoJSON `lakes` + CSV `obs`): only `lakes` survives."""
    pygeoapi_config = yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text())
    assert martin_config_from_pygeoapi(pygeoapi_config) == {
        "geojson": {"sources": {"lakes": "tests/data/ne_110m_lakes.geojson"}}
    }
    assert martin_config_from_pygeoapi({}) == {}
