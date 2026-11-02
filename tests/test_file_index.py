"""Index of the files of a GeoParquet dataset, and the files a bbox meets.

Every app import stays at module level: other test modules purge ``app.*``
from ``sys.modules`` in their fixtures, and an import inside a test would
bind a second ``FileIndexError`` that ``pytest.raises`` does not catch.
"""

import pytest
from loguru import logger

from app.provider.duckdb_ import connect, scan_files
from app.provider.file_index import (
    FileEntry,
    FileIndexError,
    read_stac_geoparquet,
    select_files,
)

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
