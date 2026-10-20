"""Naming the root of a catalog, and resolving the references its documents hold."""

from __future__ import annotations

import pytest

from fastgeoapi_portolan.catalog.locations import resolve, root_document


@pytest.mark.parametrize(
    ("location", "root"),
    [
        ("https://example.org/cat/", "https://example.org/cat/catalog.json"),
        ("https://example.org/cat", "https://example.org/cat/catalog.json"),
        ("https://example.org/cat/catalog.json", "https://example.org/cat/catalog.json"),
        ("s3://bucket/cat/", "s3://bucket/cat/catalog.json"),
    ],
)
def test_a_directory_and_its_catalog_json_name_the_same_root(location, root):
    assert root_document(location) == root


def test_a_local_directory_and_its_catalog_json_name_the_same_root(tmp_path):
    assert root_document(str(tmp_path)) == root_document(str(tmp_path / "catalog.json"))
    assert root_document(str(tmp_path)) == str((tmp_path / "catalog.json").resolve())


@pytest.mark.parametrize(
    ("document", "href", "resolved"),
    [
        (
            "https://example.org/cat/data/roads/collection.json",
            "./styles/default.json",
            "https://example.org/cat/data/roads/styles/default.json",
        ),
        (
            "https://example.org/cat/data/roads/collection.json",
            "../../../files/roads.parquet",
            "https://example.org/files/roads.parquet",
        ),
        (
            "s3://bucket/cat/data/catalog.json",
            "./roads/collection.json",
            "s3://bucket/cat/data/roads/collection.json",
        ),
        (
            "https://example.org/cat/catalog.json",
            "/files/roads.parquet",
            "https://example.org/files/roads.parquet",
        ),
        (
            "https://example.org/cat/catalog.json",
            "roads.pmtiles?version=2",
            "https://example.org/cat/roads.pmtiles?version=2",
        ),
    ],
)
def test_relative_hrefs_resolve_against_their_document(document, href, resolved):
    assert resolve(document, href) == resolved


def test_a_relative_href_in_a_local_document_resolves_to_a_path(tmp_path):
    document = str(tmp_path / "data" / "catalog.json")

    assert resolve(document, "./roads/collection.json") == str(
        tmp_path / "data" / "roads" / "collection.json"
    )
    assert resolve(document, "../files/roads.parquet") == str(tmp_path / "files" / "roads.parquet")


@pytest.mark.parametrize(
    "href", ["https://cdn.example.org/roads.pmtiles", "s3://other/roads.parquet"]
)
def test_an_absolute_href_is_kept(href):
    assert resolve("https://example.org/cat/catalog.json", href) == href


def test_an_absolute_path_in_a_local_document_is_kept(tmp_path):
    assert resolve(str(tmp_path / "catalog.json"), "/abs/roads.json") == "/abs/roads.json"


def test_a_relative_href_through_a_symlink_resolves_to_the_real_path(tmp_path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

    resolved = resolve(str(tmp_path / "catalog.json"), "./link/collection.json")

    assert resolved == str(tmp_path / "real" / "collection.json")
