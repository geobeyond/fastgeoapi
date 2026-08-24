"""Reuse pygeoapi plugin instances across requests.

``pygeoapi.plugin.load_plugin`` imports the module and instantiates the
plugin on every call, and the API modules call it per request — ten call
sites in ``itemtypes`` alone. Providers with a real constructor pay that
cost repeatedly: the GeoParquet provider spends 76 ms opening a DuckDB
session (36 ms of it loading the spatial extension) against a 2.9 ms
query, and a database-backed provider pays a connection each time.

Reuse is scoped by what the plugin declares about itself. Upstream
hands every request a fresh object, so a provider may legitimately
assume it is never used from two threads at once, and sharing one
silently would break that assumption. So:

- a plugin whose class sets ``THREAD_SAFE = True`` is shared across the
  whole process — one instance, however many requests and threads;
- everything else is cached **per thread**, which still removes the
  per-request cost while keeping the single-threaded contract.

The cache is provider-agnostic on purpose: it works for every pygeoapi
plugin type, and the opt-in flag is the whole proposal to upstream —
providers that know they are safe say so and stop being rebuilt.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import pygeoapi.api
import pygeoapi.api.coverages
import pygeoapi.api.environmental_data_retrieval
import pygeoapi.api.itemtypes
import pygeoapi.api.maps
import pygeoapi.api.processes
import pygeoapi.api.tiles
import pygeoapi.plugin

from app.config.logging import create_logger

logger = create_logger("app.pygeoapi.plugin")

# Modules that did ``from pygeoapi.plugin import load_plugin``: the name
# is bound by value there, so rebinding only `pygeoapi.plugin` would
# leave every caller on the original function.
_IMPORTERS = (
    pygeoapi.api,
    pygeoapi.api.coverages,
    pygeoapi.api.environmental_data_retrieval,
    pygeoapi.api.itemtypes,
    pygeoapi.api.maps,
    pygeoapi.api.processes,
    pygeoapi.api.tiles,
)

# Set ``THREAD_SAFE = True`` on a plugin class to opt into process-wide
# reuse. Our GeoParquet provider does: it takes a fresh DuckDB cursor per
# operation, which is that engine's documented pattern for concurrent use.
THREAD_SAFE_ATTRIBUTE = "THREAD_SAFE"

_local = threading.local()
_shared: dict[str, Any] = {}
_shared_lock = threading.Lock()
_generation = 0
_generation_lock = threading.Lock()
_hits = 0
_misses = 0


def _cache_key(plugin_type: str, plugin_def: dict) -> str | None:
    """A stable key for a plugin definition, or None when it has none.

    Definitions are plain config dictionaries, so JSON with sorted keys
    identifies them exactly. Anything that will not serialise (a live
    object passed programmatically) simply opts out of the cache rather
    than risking a wrong hit.
    """
    try:
        return f"{plugin_type}|{json.dumps(plugin_def, sort_keys=True)}"
    except (TypeError, ValueError):
        return None


def invalidate_plugin_cache() -> None:
    """Drop every cached instance, on every thread.

    Bumping a generation counter is what makes this reachable from the
    thread that handles a config reload: thread-local dictionaries owned
    by other workers cannot be cleared directly, but entries stamped
    with an older generation are ignored and rebuilt.
    """
    global _generation
    with _generation_lock:
        _generation += 1
    with _shared_lock:
        _shared.clear()
    cache = getattr(_local, "cache", None)
    if cache is not None:
        cache.clear()


def plugin_cache_stats() -> dict[str, int]:
    """Hits, misses, shared entries and generation — for tests and logging."""
    return {
        "hits": _hits,
        "misses": _misses,
        "shared": len(_shared),
        "generation": _generation,
    }


def patch_load_plugin() -> None:
    """Rebind a caching ``load_plugin`` everywhere upstream imported it."""
    if getattr(pygeoapi.plugin.load_plugin, "_fastgeoapi_cached", False):
        return

    original = pygeoapi.plugin.load_plugin

    def load_plugin(plugin_type: str, plugin_def: dict) -> Any:
        global _hits, _misses
        key = _cache_key(plugin_type, plugin_def)
        if key is None:
            _misses += 1
            return original(plugin_type, plugin_def)

        with _shared_lock:
            shared = _shared.get(key)
        if shared is not None:
            _hits += 1
            return shared

        cache = getattr(_local, "cache", None)
        if cache is None or getattr(_local, "generation", None) != _generation:
            cache = {}
            _local.cache = cache
            _local.generation = _generation

        if key in cache:
            _hits += 1
            return cache[key]

        _misses += 1
        instance = original(plugin_type, plugin_def)
        if getattr(type(instance), THREAD_SAFE_ATTRIBUTE, False):
            with _shared_lock:
                _shared[key] = instance
        else:
            cache[key] = instance
        return instance

    # ty flags these rebindings because the replacement is a different
    # function object than the one declared upstream; substituting a
    # module attribute at runtime is exactly what a patch does, and the
    # signature is identical.
    load_plugin._fastgeoapi_cached = True
    pygeoapi.plugin.load_plugin = load_plugin  # ty: ignore[invalid-assignment]
    for module in _IMPORTERS:
        if hasattr(module, "load_plugin"):
            module.load_plugin = load_plugin  # ty: ignore[invalid-assignment]
    logger.debug("pygeoapi plugin instances are now reused between requests")
