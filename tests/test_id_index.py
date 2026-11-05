"""An id index the data publisher ships, and the lookup of one id in it.

Every app import stays at module level: other test modules purge ``app.*``
from ``sys.modules`` in their fixtures. ``duckdb`` is imported inside the
tests that need it: the renderer lane collects this module without it.
"""

from unittest.mock import patch

import pytest
from loguru import logger

from app.provider import id_index as id_index_module
from app.provider.duckdb_ import connect
from app.provider.id_index import IdIndexError, IdRow, RetrievedIdIndex, look_up_id

LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _write_part(path, ids) -> None:
    """One file of an index in the registry form: id, path, bbox, sorted by id."""
    selects = [
        f"SELECT '{identifier}' AS id,"
        f" {'NULL' if identifier == 'k' else repr(f'theme=x/part-{identifier}.parquet')} AS path,"
        f" {{'xmin': {n}.0, 'xmax': {n}.5, 'ymin': 1.0, 'ymax': 1.5}} AS bbox"
        for n, identifier in enumerate(ids)
    ]
    query = " UNION ALL ".join(selects) + " ORDER BY id"
    connect(str(path.parent)).execute(f"COPY ({query}) TO '{path}' (FORMAT parquet)")


@pytest.fixture
def registry(tmp_path):
    folder = tmp_path / "registry"
    folder.mkdir()
    _write_part(folder / "part-0.parquet", LETTERS[:13])
    _write_part(folder / "part-1.parquet", LETTERS[13:])
    return RetrievedIdIndex.from_definition(
        {
            "type": "retrieved",
            "location": f"{folder}/*.parquet",
            "columns": {"id": "id", "path": "path", "bbox": "bbox"},
            "href_base": "s3://bucket/release/1/",
        }
    )


def test_a_known_id_gives_its_href_and_bbox(registry, tmp_path):
    row = look_up_id(registry, "c", cache_dir=tmp_path / "cache")

    assert row == IdRow(
        href="s3://bucket/release/1/theme=x/part-c.parquet", bbox=(2.0, 1.0, 2.5, 1.5)
    )


def test_an_unknown_id_gives_none(registry, tmp_path):
    assert look_up_id(registry, "cc", cache_dir=tmp_path / "cache") is None


def test_a_row_without_a_path_gives_no_href(registry, tmp_path):
    row = look_up_id(registry, "k", cache_dir=tmp_path / "cache")

    assert row is not None
    assert row.href is None


def test_only_the_file_whose_range_holds_the_id_is_read(registry, tmp_path):
    with patch.object(id_index_module, "_query_file", wraps=id_index_module._query_file) as queries:
        look_up_id(registry, "q", cache_dir=tmp_path / "cache")

    assert [call.args[0].rsplit("/", 1)[-1] for call in queries.call_args_list] == [
        "part-1.parquet"
    ]


def test_an_id_outside_every_range_opens_no_file(registry, tmp_path):
    with patch.object(id_index_module, "_query_file") as queries:
        assert look_up_id(registry, "0", cache_dir=tmp_path / "cache") is None
        assert look_up_id(registry, "zz", cache_dir=tmp_path / "cache") is None

    assert queries.call_count == 0


def test_the_ranges_come_from_the_cache_when_the_listing_is_unchanged(registry, tmp_path):
    cache = tmp_path / "cache"
    with patch.object(id_index_module, "_read_range", wraps=id_index_module._read_range) as ranges:
        look_up_id(registry, "c", cache_dir=cache)
        look_up_id(registry, "q", cache_dir=cache)

    assert ranges.call_count == 2


def test_an_id_with_quotes_is_looked_up_as_a_parameter(registry, tmp_path):
    assert look_up_id(registry, "c' OR '1'='1", cache_dir=tmp_path / "cache") is None


def test_a_generated_index_is_ignored_with_a_warning():
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        index = RetrievedIdIndex.from_definition(
            {"type": "generated", "method": "bloom", "location": "indexes/a.ids.bloom"}
        )
    finally:
        logger.remove(sink)

    assert index is None
    assert any("generated" in message for message in messages)


@pytest.mark.parametrize(
    "definition",
    [
        {"type": "retrieved", "location": "a/*.parquet", "columns": {"path": "path"}},
        {"type": "retrieved", "location": "a/*.parquet", "columns": {"id": "id"}},
        {"type": "retrieved", "location": "a/*.parquet", "columns": {"id": "id", "path": "p"}},
        {"type": "other", "location": "a/*.parquet", "columns": {"id": "id", "href": "h"}},
    ],
)
def test_a_malformed_mapping_is_refused(definition):
    with pytest.raises(IdIndexError):
        RetrievedIdIndex.from_definition(definition)


def test_a_file_without_statistics_is_searched(registry, tmp_path):
    with patch.object(id_index_module, "_read_range", return_value=("VARCHAR", None, None)):
        row = look_up_id(registry, "c", cache_dir=tmp_path / "cache")

    assert row is not None
    assert row.href == "s3://bucket/release/1/theme=x/part-c.parquet"


def test_an_id_column_of_another_type_is_searched(registry, tmp_path):
    with patch.object(id_index_module, "_read_range", return_value=("BLOB", "a", "m")):
        assert look_up_id(registry, "c", cache_dir=tmp_path / "cache") is not None


def test_a_location_that_cannot_be_listed_is_an_id_index_error(tmp_path):
    index = RetrievedIdIndex.from_definition(
        {
            "type": "retrieved",
            "location": f"{tmp_path}/missing/*.parquet",
            "columns": {"id": "id", "href": "href"},
        }
    )

    with pytest.raises(IdIndexError):
        look_up_id(index, "c", cache_dir=tmp_path / "cache")
