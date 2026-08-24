"""Reuse pygeoapi plugin instances instead of rebuilding them per request.

``pygeoapi.plugin.load_plugin`` imports the module and instantiates the
plugin on every call, and the API modules call it on every request — ten
call sites in ``itemtypes`` alone. Any provider with a non-trivial
constructor pays that repeatedly: our GeoParquet provider spends 76 ms
opening a DuckDB session (36 ms of it loading the spatial extension)
against a 2.9 ms query, and a database-backed provider pays a connection.

Reuse is scoped by what the plugin declares. Upstream hands every
request a fresh instance, so a provider may assume it is never used
concurrently: sharing one silently would break that. A class that sets
``THREAD_SAFE = True`` is shared process-wide; everything else is cached
per thread, which still removes the per-request construction while
keeping the single-threaded contract.
"""

import threading

import pytest

from app.pygeoapi.plugin import (
    invalidate_plugin_cache,
    patch_load_plugin,
    plugin_cache_stats,
)

FEATURE_DEF = {
    "type": "feature",
    "name": "app.provider.geoparquet.GeoParquetProvider",
}


@pytest.fixture
def dataset(tmp_path_factory) -> str:
    from app.provider.duckdb_ import connect

    root = tmp_path_factory.mktemp("plugincache")
    con = connect(str(root))
    con.execute(
        f"""
        COPY (SELECT 1 AS id, 'a' AS name, ST_Point(1, 2) AS geom)
        TO '{root}/ds.parquet' (FORMAT parquet)
        """
    )
    return f"{root}/ds.parquet"


@pytest.fixture(autouse=True)
def fresh_cache():
    patch_load_plugin()
    invalidate_plugin_cache()
    yield
    invalidate_plugin_cache()


def _definition(dataset: str) -> dict:
    return {**FEATURE_DEF, "data": dataset, "id_field": "id", "geometry_column": "geom"}


def test_the_same_definition_yields_the_same_instance(dataset):
    from pygeoapi.plugin import load_plugin

    first = load_plugin("provider", _definition(dataset))
    second = load_plugin("provider", _definition(dataset))
    assert first is second


def test_a_different_definition_yields_a_different_instance(dataset):
    from pygeoapi.plugin import load_plugin

    first = load_plugin("provider", _definition(dataset))
    other = dict(_definition(dataset), id_field="name")
    assert load_plugin("provider", other) is not first


def test_invalidation_drops_the_instances(dataset):
    """A config reload must not keep serving providers built from the old one."""
    from pygeoapi.plugin import load_plugin

    first = load_plugin("provider", _definition(dataset))
    invalidate_plugin_cache()
    assert load_plugin("provider", _definition(dataset)) is not first


def test_a_thread_safe_plugin_is_shared_across_threads(dataset):
    """Declaring THREAD_SAFE is what buys process-wide reuse."""
    from pygeoapi.plugin import load_plugin

    from app.provider.geoparquet import GeoParquetProvider

    assert GeoParquetProvider.THREAD_SAFE is True
    definition = _definition(dataset)
    main = load_plugin("provider", definition)
    seen: list[object] = []

    thread = threading.Thread(target=lambda: seen.append(load_plugin("provider", definition)))
    thread.start()
    thread.join()

    assert seen[0] is main


def test_a_plugin_without_the_flag_stays_per_thread(tmp_path):
    """Default safety: an undeclared plugin is never shared across threads.

    Upstream gives every request a fresh instance, so a provider may hold
    state that was never meant to be touched concurrently. Reuse within a
    thread still removes the per-request construction.
    """
    from pygeoapi.plugin import load_plugin

    source = tmp_path / "points.geojson"
    source.write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature", "id": "1",'
        ' "geometry": {"type": "Point", "coordinates": [1, 2]}, "properties": {}}]}'
    )
    definition = {
        "type": "feature",
        "name": "GeoJSON",
        "data": str(source),
        "id_field": "id",
    }
    provider = load_plugin("provider", definition)
    assert getattr(type(provider), "THREAD_SAFE", False) is False

    seen: list[object] = []

    def worker():
        seen.append(load_plugin("provider", definition))
        seen.append(load_plugin("provider", definition))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert seen[0] is seen[1]  # reused within that thread
    assert seen[0] is not provider  # but never shared with another one


def test_an_unhashable_definition_still_works(dataset):
    """A definition that cannot be keyed falls back to building it."""
    from pygeoapi.plugin import load_plugin

    definition = dict(_definition(dataset), store_options={"opaque": object()})
    provider = load_plugin("provider", definition)
    assert provider is not None


def test_patching_is_idempotent(dataset):
    from pygeoapi.plugin import load_plugin

    patch_load_plugin()
    patch_load_plugin()
    first = load_plugin("provider", _definition(dataset))
    assert load_plugin("provider", _definition(dataset)) is first


def test_stats_report_hits_and_misses(dataset):
    from pygeoapi.plugin import load_plugin

    load_plugin("provider", _definition(dataset))
    load_plugin("provider", _definition(dataset))
    stats = plugin_cache_stats()
    assert stats["misses"] >= 1
    assert stats["hits"] >= 1
