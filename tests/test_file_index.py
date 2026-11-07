"""Index of the files of a GeoParquet dataset, and the files a bbox meets.

Every app import stays at module level: other test modules purge ``app.*``
from ``sys.modules`` in their fixtures, and an import inside a test would
bind a second ``FileIndexError`` that ``pytest.raises`` does not catch.
"""

import json
from unittest.mock import patch

import pytest
from loguru import logger

from app.provider import file_index as file_index_module
from app.provider.duckdb_ import connect, scan_files
from app.provider.file_index import (
    FileEntry,
    FileIndexError,
    count_rows,
    read_file_index,
    read_stac_collection,
    read_stac_geoparquet,
    resolve_href,
    select_files,
    select_page,
)
from app.provider.storage.cache import digest

#: One point per file, in three boxes that do not touch.
BOXES = {"a": (0.0, 0.0, 1.0, 1.0), "b": (10.0, 10.0, 11.0, 11.0), "c": (20.0, 20.0, 21.0, 21.0)}


def _write_index(path, rows, *, asset="data") -> str:
    """A stac-geoparquet index: ``rows`` are ``(id, bbox mapping, href)``."""
    con = connect(str(path.parent))
    selects = [
        f"SELECT '{identifier}' AS id, {bbox!r} AS bbox, {{'{asset}': {{'href': '{href}'}}}} AS assets"
        for identifier, bbox, href in rows
    ]
    con.execute(f"COPY ({' UNION ALL '.join(selects)}) TO '{path}' (FORMAT parquet)")
    return str(path)


def _planar(box) -> dict:
    xmin, ymin, xmax, ymax = box
    return {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax}


@pytest.fixture
def dataset(tmp_path):
    """Three files, one point each, and an index whose hrefs are relative to it."""
    con = connect(str(tmp_path))
    for number, (name, (xmin, ymin, _, _)) in enumerate(BOXES.items(), start=1):
        con.execute(
            f"COPY (SELECT {number} AS id, ST_Point({xmin + 0.5}, {ymin + 0.5}) AS geom)"
            f" TO '{tmp_path}/{name}.parquet' (FORMAT parquet)"
        )
    index = _write_index(
        tmp_path / "index.parquet",
        [(name, _planar(box), f"{name}.parquet") for name, box in BOXES.items()],
    )
    return tmp_path, index


def test_the_index_lists_one_entry_per_row(dataset):
    root, index = dataset

    entries = read_stac_geoparquet(index)

    assert sorted(entry.href for entry in entries) == [
        str(root / f"{name}.parquet") for name in BOXES
    ]
    assert {entry.bbox for entry in entries} == set(BOXES.values())


def test_a_bbox_selects_only_the_files_it_meets(dataset):
    root, index = dataset

    selected = select_files(read_stac_geoparquet(index), [10.2, 10.2, 10.4, 10.4])

    assert selected == [str(root / "b.parquet")]


def test_without_a_bbox_every_file_is_selected(dataset):
    _, index = dataset

    assert len(select_files(read_stac_geoparquet(index), None)) == 3


def test_an_antimeridian_bbox_keeps_the_files_on_both_sides():
    east = FileEntry(href="east.parquet", bbox=(179.0, 0.0, 180.0, 1.0))
    west = FileEntry(href="west.parquet", bbox=(-180.0, 0.0, -179.0, 1.0))
    middle = FileEntry(href="middle.parquet", bbox=(0.0, 0.0, 1.0, 1.0))

    selected = select_files([east, west, middle], [178.0, 0.0, -178.0, 1.0])

    assert selected == ["east.parquet", "west.parquet"]


def test_a_six_value_bbox_uses_its_planar_corners(tmp_path):
    three_d = {"xmin": 1.0, "ymin": 2.0, "zmin": -5.0, "xmax": 3.0, "ymax": 4.0, "zmax": 5.0}
    index = _write_index(tmp_path / "index.parquet", [("a", three_d, "a.parquet")])

    (entry,) = read_stac_geoparquet(index)

    assert entry.bbox == (1.0, 2.0, 3.0, 4.0)


def test_an_index_without_the_asset_names_the_missing_column(tmp_path):
    index = _write_index(
        tmp_path / "index.parquet", [("a", _planar(BOXES["a"]), "a.parquet")], asset="visual"
    )

    with pytest.raises(FileIndexError, match=r"assets\.data\.href"):
        read_stac_geoparquet(index)


def test_an_href_with_a_quote_stays_one_literal(tmp_path):
    path = tmp_path / "it's.parquet"
    con = connect(str(tmp_path))
    con.execute(
        f"COPY (SELECT 1 AS id) TO '{str(path).replace(chr(39), chr(39) * 2)}' (FORMAT parquet)"
    )

    scan = scan_files([str(path)])

    assert str(path).replace("'", "''") in scan
    assert con.execute(f"SELECT count(*) FROM {scan}").fetchone()[0] == 1


def _write_sql_index(path, select: str) -> str:
    connect(str(path.parent)).execute(f"COPY ({select}) TO '{path}' (FORMAT parquet)")
    return str(path)


def _warnings(action) -> list[str]:
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        action()
    finally:
        logger.remove(sink)
    return messages


def test_a_row_without_an_href_names_its_id(tmp_path):
    index = _write_sql_index(
        tmp_path / "index.parquet",
        "SELECT 'a' AS id, {'xmin': 0.0, 'ymin': 0.0, 'xmax': 1.0, 'ymax': 1.0} AS bbox,"
        " {'data': {'href': 'a.parquet'}} AS assets"
        " UNION ALL SELECT 'b', {'xmin': 1.0, 'ymin': 1.0, 'xmax': 2.0, 'ymax': 2.0},"
        " {'data': {'href': NULL::VARCHAR}}",
    )

    with pytest.raises(FileIndexError, match="'b'"):
        read_stac_geoparquet(index)


def test_rows_with_an_unusable_bbox_are_kept_and_counted_in_a_warning(tmp_path):
    index = _write_sql_index(
        tmp_path / "index.parquet",
        "SELECT 'a' AS id, {'xmin': 0.0, 'ymin': 0.0, 'xmax': 1.0, 'ymax': 1.0} AS bbox,"
        " {'data': {'href': 'a.parquet'}} AS assets"
        " UNION ALL SELECT 'b', NULL, {'data': {'href': 'b.parquet'}}",
    )
    entries: list[FileEntry] = []

    messages = _warnings(lambda: entries.extend(read_stac_geoparquet(index)))

    assert select_files(entries, [50.0, 50.0, 51.0, 51.0]) == [str(tmp_path / "b.parquet")]
    assert any("1 of 2" in message for message in messages)


def test_an_index_without_stac_geoparquet_metadata_is_read_with_a_warning(dataset):
    _, index = dataset

    messages = _warnings(lambda: read_stac_geoparquet(index))

    assert any("stac-geoparquet" in message and index in message for message in messages)


def test_an_index_without_ids_names_that_column(tmp_path):
    index = _write_sql_index(
        tmp_path / "index.parquet",
        "SELECT {'xmin': 0.0, 'ymin': 0.0, 'xmax': 1.0, 'ymax': 1.0} AS bbox,"
        " {'data': {'href': 'a.parquet'}} AS assets",
    )

    with pytest.raises(FileIndexError, match=r"has no id$"):
        read_stac_geoparquet(index)


def _write_collection(root, items) -> str:
    """A STAC collection whose ``item`` links name one JSON item per ``(id, bbox, href)``."""
    (root / "items").mkdir(exist_ok=True)
    links = []
    for identifier, bbox, href in items:
        item = {"type": "Feature", "id": identifier, "assets": {"data": {"href": href}}}
        if bbox is not None:
            item["bbox"] = bbox
        (root / "items" / f"{identifier}.json").write_text(json.dumps(item))
        links.append({"rel": "item", "href": f"./items/{identifier}.json"})
    collection = root / "collection.json"
    collection.write_text(json.dumps({"type": "Collection", "id": "roads", "links": links}))
    return str(collection)


ITEMS = [
    ("a", [0.0, 0.0, 1.0, 1.0], "../a.parquet"),
    ("b", [10.0, 10.0, 11.0, 11.0], "../b.parquet"),
    ("c", [20.0, 20.0, 21.0, 21.0], "../c.parquet"),
]


def test_a_collection_index_reads_its_items(tmp_path):
    collection = _write_collection(tmp_path, ITEMS)

    entries = read_stac_collection(collection)

    assert [entry.href for entry in entries] == [
        str(tmp_path / f"{name}.parquet") for name in "abc"
    ]
    assert entries[1].bbox == (10.0, 10.0, 11.0, 11.0)


def test_a_second_read_comes_from_the_cache(tmp_path):
    collection = _write_collection(tmp_path, ITEMS)
    cache = tmp_path / "cache"

    with patch.object(
        file_index_module, "read_stac_item", wraps=file_index_module.read_stac_item
    ) as reads:
        first = read_stac_collection(collection, cache_dir=cache)
        second = read_stac_collection(collection, cache_dir=cache)

    assert reads.call_count == 3
    assert second == first


def test_a_changed_collection_is_read_again(tmp_path):
    collection = _write_collection(tmp_path, ITEMS)
    cache = tmp_path / "cache"
    read_stac_collection(collection, cache_dir=cache)
    _write_collection(tmp_path, ITEMS[:2])

    entries = read_stac_collection(collection, cache_dir=cache)

    assert len(entries) == 2


def test_an_item_without_a_bbox_is_always_selected(tmp_path):
    collection = _write_collection(tmp_path, [*ITEMS[:2], ("d", None, "../d.parquet")])

    selected = select_files(read_stac_collection(collection), [50.0, 50.0, 51.0, 51.0])

    assert selected == [str(tmp_path / "d.parquet")]


def test_the_index_kind_follows_the_suffix(dataset, tmp_path):
    _, index = dataset
    stac = tmp_path / "stac"
    stac.mkdir()
    collection = _write_collection(stac, ITEMS)

    assert len(read_file_index(index)) == 3
    assert len(read_file_index(collection)) == 3


def test_a_missing_index_is_a_file_index_error(tmp_path):
    with pytest.raises(FileIndexError, match="cannot be read"):
        read_file_index(str(tmp_path / "missing.parquet"))


@pytest.mark.parametrize(
    ("href", "base", "expected"),
    [
        ("./items/a.json", "s3://b/c/collection.json", "s3://b/c/items/a.json"),
        ("../part-0.parquet", "s3://b/c/meta/index.parquet", "s3://b/c/part-0.parquet"),
        ("part-0.parquet", "https://h/c/index.parquet", "https://h/c/part-0.parquet"),
        ("s3://other/part-0.parquet", "s3://b/c/index.parquet", "s3://other/part-0.parquet"),
    ],
)
def test_a_relative_href_resolves_against_a_remote_index(href, base, expected):
    assert resolve_href(href, base) == expected


@pytest.mark.parametrize("href", ["/etc/data.parquet", "file:///etc/data.parquet"])
def test_a_remote_index_cannot_name_a_local_file(href):
    with pytest.raises(FileIndexError, match="local"):
        resolve_href(href, "s3://b/c/index.parquet")


def test_a_local_index_can_name_an_absolute_path(tmp_path):
    assert resolve_href("/data/a.parquet", str(tmp_path / "index.parquet")) == "/data/a.parquet"


def test_a_file_across_the_antimeridian_is_kept_for_both_sides():
    across = FileEntry(href="across.parquet", bbox=(170.0, -10.0, -170.0, 10.0))

    assert select_files([across], [175.0, -5.0, 178.0, 5.0]) == ["across.parquet"]
    assert select_files([across], [-178.0, -5.0, -175.0, 5.0]) == ["across.parquet"]
    assert select_files([across], [175.0, -5.0, -175.0, 5.0]) == ["across.parquet"]
    assert select_files([across], [0.0, -5.0, 1.0, 5.0]) == []


def _counted_index(path, counts) -> str:
    """An index of one row per count, ``NULL`` where the count is None."""
    selects = [
        f"SELECT '{name}' AS id,"
        f" {{'xmin': {n}.0, 'ymin': 0.0, 'xmax': {n}.5, 'ymax': 1.0}} AS bbox,"
        f" {{'data': {{'href': '{name}.parquet'}}}} AS assets,"
        f' {"NULL" if count is None else count}::BIGINT AS "table:row_count"'
        for n, (name, count) in enumerate(counts.items())
    ]
    return _write_sql_index(path, " UNION ALL ".join(selects))


def test_the_index_reads_the_row_count_of_each_file(tmp_path):
    index = _counted_index(tmp_path / "index.parquet", {"a": 1, "b": 2, "c": 3})

    assert [entry.rows for entry in read_stac_geoparquet(index)] == [1, 2, 3]


def test_an_index_without_row_counts_reads_none(dataset):
    _, index = dataset

    assert {entry.rows for entry in read_stac_geoparquet(index)} == {None}


def test_a_count_that_is_not_a_count_reads_as_missing(tmp_path):
    index = _counted_index(tmp_path / "index.parquet", {"a": None, "b": -1, "c": 4})

    assert [entry.rows for entry in read_stac_geoparquet(index)] == [None, None, 4]


def _set_row_count(root, identifier, count) -> None:
    item = root / "items" / f"{identifier}.json"
    document = json.loads(item.read_text())
    document["properties"] = {"table:row_count": count}
    item.write_text(json.dumps(document))


@pytest.mark.parametrize(("count", "expected"), [(7, 7), (True, None), (3.5, None), ("7", None)])
def test_a_collection_item_gives_its_row_count(tmp_path, count, expected):
    collection = _write_collection(tmp_path, ITEMS)
    _set_row_count(tmp_path, "b", count)

    entries = read_stac_collection(collection)

    assert [entry.rows for entry in entries] == [None, expected, None]


def test_the_cache_keeps_the_row_counts(tmp_path):
    collection = _write_collection(tmp_path, ITEMS)
    _set_row_count(tmp_path, "a", 5)
    cache = tmp_path / "cache"

    read_stac_collection(collection, cache_dir=cache)
    with patch.object(file_index_module, "read_stac_item") as reads:
        cached = read_stac_collection(collection, cache_dir=cache)

    assert reads.call_count == 0
    assert [entry.rows for entry in cached] == [5, None, None]


def test_a_cache_written_without_row_counts_is_read_again(tmp_path):
    collection = _write_collection(tmp_path, ITEMS)
    _set_row_count(tmp_path, "a", 5)
    cache = tmp_path / "cache"
    old = cache / "file-index" / f"{digest(collection + 'data')}.json"
    old.parent.mkdir(parents=True)
    etag = file_index_module._etag(collection, None)
    hrefs = [str(tmp_path / f"{name}.parquet") for name in "abc"]
    old.write_text(json.dumps({"etag": etag, "entries": [[href, None] for href in hrefs]}))

    with patch.object(
        file_index_module, "read_stac_item", wraps=file_index_module.read_stac_item
    ) as reads:
        entries = read_stac_collection(collection, cache_dir=cache)

    assert reads.call_count == 3
    assert [entry.rows for entry in entries] == [5, None, None]


COUNTED = [
    FileEntry(href=name, bbox=None, rows=rows)
    for name, rows in (("a", 3), ("b", 0), ("c", 4), ("d", 5))
]


def test_count_rows_sums_the_counts():
    assert count_rows(COUNTED) == 12
    assert count_rows([*COUNTED, FileEntry(href="e", bbox=None)]) is None


def test_select_page_starts_in_the_file_that_holds_the_offset():
    assert select_page(COUNTED, 4, 2) == (["c"], 1)


def test_select_page_spans_files():
    assert select_page(COUNTED, 2, 3) == (["a", "c"], 2)


def test_select_page_past_the_end_is_empty():
    assert select_page(COUNTED, 12, 10) == ([], 0)
    assert select_page(COUNTED, 0, 0) == ([], 0)


def test_an_index_written_by_the_ingest_gives_its_row_counts(tmp_path):
    writer = pytest.importorskip("fastgeoapi_portolan.file_index")
    location = str(tmp_path / "index.parquet")
    writer.write_index(
        [
            writer.IndexRow(id="a", bbox=(0.0, 0.0, 1.0, 1.0), href="a.parquet", rows=2),
            writer.IndexRow(id="b", bbox=(2.0, 2.0, 3.0, 3.0), href="b.parquet", rows=3),
        ],
        location,
    )

    entries = read_stac_geoparquet(location)

    assert [entry.rows for entry in entries] == [2, 3]
    assert count_rows(entries) == 5
