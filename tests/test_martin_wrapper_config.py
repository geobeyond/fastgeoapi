"""`_martin_config_from_pygeoapi` (app/tiles/martin_wrapper.py).

Pure dict translation — no `martin_py` involved — so unlike
`test_martin_wrapper.py` these run regardless of whether the
`martin_wrapper` extra is installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.tiles.martin_wrapper import _martin_config_from_pygeoapi


def test_geojson_provider_becomes_a_geojson_source():
    config = {
        "resources": {
            "lakes": {
                "type": "collection",
                "providers": [
                    {"type": "feature", "name": "GeoJSON", "data": "tests/data/lakes.geojson"}
                ],
            }
        }
    }
    assert _martin_config_from_pygeoapi(config) == {
        "geojson": {"sources": {"lakes": "tests/data/lakes.geojson"}}
    }


def test_geoparquet_provider_becomes_a_duckdb_source():
    config = {
        "resources": {
            "parcels": {
                "type": "collection",
                "providers": [
                    {
                        "type": "feature",
                        "name": "app.provider.geoparquet.GeoParquetProvider",
                        "data": "tests/data/parcels.parquet",
                        "id_field": "id",
                        "geometry_column": "wkb_geometry",
                        "storage_crs": "http://www.opengis.net/def/crs/EPSG/0/3857",
                    }
                ],
            }
        }
    }
    assert _martin_config_from_pygeoapi(config) == {
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


def test_geoparquet_provider_defaults_geometry_column_and_srid():
    config = {
        "resources": {
            "parcels": {
                "providers": [
                    {
                        "type": "feature",
                        "name": "Parquet",
                        "data": "tests/data/parcels.parquet",
                    }
                ]
            }
        }
    }
    source = _martin_config_from_pygeoapi(config)["duckdb"]["sources"][0]
    assert source["geometry_column"] == "geom"
    assert source["srid"] == 4326


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("s3://bucket/theme=places/", "s3://bucket/theme=places/**/*.parquet"),
        ("s3://bucket/theme=places", "s3://bucket/theme=places/**/*.parquet"),
        ("s3://bucket/places.parquet", "s3://bucket/places.parquet"),
        ("s3://bucket/part-*.parquet", "s3://bucket/part-*.parquet"),
        ("tests/data/parcels", "tests/data/parcels"),
    ],
)
def test_remote_geoparquet_directory_becomes_a_glob(data, expected):
    config = {
        "resources": {
            "places": {
                "providers": [
                    {
                        "type": "feature",
                        "name": "app.provider.geoparquet.GeoParquetProvider",
                        "data": data,
                    }
                ]
            }
        }
    }
    source = _martin_config_from_pygeoapi(config)["duckdb"]["sources"][0]
    assert source["geoparquet"] == expected


def test_pmtiles_detected_by_extension_regardless_of_provider_name():
    config = {
        "resources": {
            "basemap": {
                "providers": [
                    {"type": "tile", "name": "MVT-proxy", "data": "tests/data/basemap.pmtiles"}
                ]
            }
        }
    }
    assert _martin_config_from_pygeoapi(config) == {
        "pmtiles": {"sources": {"basemap": "tests/data/basemap.pmtiles"}}
    }


def test_unmanageable_providers_are_skipped():
    config = {
        "resources": {
            "obs": {
                "providers": [{"type": "feature", "name": "CSV", "data": "tests/data/obs.csv"}]
            },
            "roads": {
                "providers": [
                    {
                        "type": "feature",
                        "name": "PostgreSQL",
                        "data": {"host": "localhost", "dbname": "gis"},
                    }
                ]
            },
        }
    }
    assert _martin_config_from_pygeoapi(config) == {}


def test_no_resources_returns_empty_dict():
    assert _martin_config_from_pygeoapi({}) == {}
    assert _martin_config_from_pygeoapi({"resources": {}}) == {}


def test_mixed_resources_only_the_manageable_ones_are_included():
    config = {
        "resources": {
            "obs": {
                "providers": [{"type": "feature", "name": "CSV", "data": "tests/data/obs.csv"}]
            },
            "lakes": {
                "providers": [
                    {"type": "feature", "name": "GeoJSON", "data": "tests/data/lakes.geojson"}
                ]
            },
        }
    }
    assert _martin_config_from_pygeoapi(config) == {
        "geojson": {"sources": {"lakes": "tests/data/lakes.geojson"}}
    }


def test_against_the_repo_test_fixture():
    """The real fixture (GeoJSON `lakes` + CSV `obs`): only `lakes` survives."""
    pygeoapi_config = yaml.safe_load(Path("tests/data/pygeoapi-config.yml").read_text())
    assert _martin_config_from_pygeoapi(pygeoapi_config) == {
        "geojson": {"sources": {"lakes": "tests/data/ne_110m_lakes.geojson"}}
    }
