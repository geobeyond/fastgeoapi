"""The document types generated from the STAC and extension schemas."""

from __future__ import annotations

import json
import subprocess  # ruff: ignore[suspicious-subprocess-import]
import sys
from importlib.resources import files
from pathlib import Path

import pytest

from fastgeoapi_portolan.catalog.types import Asset, CollectionDocument, Link

DATA = Path(__file__).parent / "data"


def test_the_core_imports_without_typing_extensions():
    # Python 3.10 has no NotRequired in typing; the core must not need the backport.
    code = (
        "import sys; sys.modules['typing_extensions'] = None; "
        "import fastgeoapi_portolan.catalog.types"
    )

    result = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] # nosec B603
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


def test_extension_fields_are_typed():
    collection_keys = set(CollectionDocument.__annotations__)
    asset_keys = set(Asset.__annotations__)

    assert {
        "stac_extensions",
        "extent",
        "links",
        "assets",
        "table:columns",
        "table:primary_geometry",
        "partition:glob",
    } <= collection_keys
    assert {"href", "type", "roles", "file:size", "file:checksum", "alternate"} <= asset_keys


def test_the_hand_typed_pmtiles_field_is_the_one_the_schema_defines():
    # web-map-links defines it under a condition the generator does not follow.
    schema = files("fastgeoapi_portolan.catalog.schemas").joinpath(
        "extensions", "stac-extensions.github.io", "web-map-links", "v1.3.0", "schema.json"
    )

    assert '"pmtiles:layers"' in schema.read_text()
    assert "pmtiles:layers" in Link.__annotations__


def test_the_models_round_trip_a_collection():
    pytest.importorskip("pydantic")
    from fastgeoapi_portolan.models import CollectionModel

    document = json.loads((DATA / "collection-alternate-assets.json").read_text())

    model = CollectionModel.model_validate(document)

    assert model.model_dump(mode="json", by_alias=True, exclude_unset=True) == document
