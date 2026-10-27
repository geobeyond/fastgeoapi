"""In-process tile wrapper around martin-py (opt-in, off by default).

`martin-py` (https://martin.maplibre.org/) is a PyO3 binding onto
Martin's own tile-serving code: given the same Martin config file it
resolves sources once at load time and serves `/{source_ids}/{z}/{x}/{y}`
tiles directly, with no HTTP hop. Mounted at `/martin-wrapper`, it lets
the two tile paths — pygeoapi's provider and martin's — be measured
against each other under the very same process and load generator.

`martin-py` is an optional dependency (the `martin_wrapper` extra): it
ships as a locally-built wheel, not yet on PyPI (see `[tool.uv.sources]`
in `pyproject.toml`). `TileServer` is `None` when it isn't installed, so
callers can check for that before mounting rather than importing this
module and getting an `ImportError`.

Unauthenticated by design: this mount carries none of the auth
middleware `main._wrap_pygeoapi_asgi` wraps the pygeoapi/admin surfaces
with. It stays out of service unless an operator explicitly points
`FASTGEOAPI_MARTIN_WRAPPER_CONFIG` at a Martin config file (or sets it
to ``auto``, see `build_martin_wrapper_app_from_pygeoapi`), and it must
never be enabled on a public deployment.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from app.config.logging import create_logger
from app.provider.storage.factory import _for_obstore

logger = create_logger("app.tiles.martin_wrapper")

try:
    from martin_py import TileServer
except ImportError:  # pragma: no cover - exercised only without the extra installed
    TileServer = None

# pygeoapi provider `name` values whose `data` is a file martin-py's
# `geojson`/`duckdb` source kinds (this build's feature set — see the
# module docstring) can open directly. Everything else — CSV, OGR/GPKG,
# PostgreSQL, MVT-* (mbtiles/postgres/elastic/proxy), rasterio, xarray,
# SensorThings, ... — has no martin-py equivalent here and is skipped.
_GEOJSON_PROVIDER_NAMES = frozenset({"GeoJSON"})
_DUCKDB_PROVIDER_NAMES = frozenset({"app.provider.geoparquet.GeoParquetProvider", "Parquet"})

_DEFAULT_SRID = 4326
_EPSG_SUFFIX = re.compile(r"EPSG/\d+/(\d+)$")


def _srid_from_storage_crs(provider: dict) -> int:
    """Best-effort EPSG code from a pygeoapi ``storage_crs`` URI.

    pygeoapi's ``storage_crs`` is an OGC CRS URI
    (``.../def/crs/EPSG/0/4326``), not a bare EPSG code; ``CRS84`` and an
    absent key both mean "geographic WGS 84", which is EPSG:4326 anyway.

    Parameters
    ----------
    provider : dict
        One provider definition from a pygeoapi resource.

    Returns
    -------
    int
        The EPSG code, or 4326 when the URI carries none.
    """
    match = _EPSG_SUFFIX.search(provider.get("storage_crs", ""))
    return int(match.group(1)) if match else _DEFAULT_SRID


def _geoparquet_location(data: str) -> str:
    """A remote directory as the glob martin's ``read_parquet`` needs.

    Martin hands a remote location straight to DuckDB's ``read_parquet``,
    which reads a trailing-slash URL as one object and gets a 404 for it,
    so a bucket prefix is expanded the way ``duckdb_.scan_expression``
    does for the native reader. A local path is left alone: martin only
    accepts an existing file there, never a directory or a glob.

    Parameters
    ----------
    data : str
        A GeoParquet provider's ``data``: file, glob or directory.

    Returns
    -------
    str
        The location to give martin as ``geoparquet``.
    """
    if "://" not in data or data.endswith(".parquet") or "*" in data:
        return data
    return f"{data.rstrip('/')}/**/*.parquet"


def _layer_id_from_data(data: str, fallback: str) -> str:
    """The GeoParquet file's basename, without its extension, as layer id.

    ``s3://bucket/overture/transportation-lazio.parquet`` (or
    ``.geoparquet``) gives ``transportation-lazio``. Any location not
    ending in ``.parquet`` or ``.geoparquet`` (a directory, a bucket
    prefix) and a last segment that is a glob (``*.parquet``) name no
    single file, so ``fallback`` is used then.

    Parameters
    ----------
    data : str
        A GeoParquet provider's ``data``: file, glob or directory.
    fallback : str
        The id to use when the basename names nothing (the resource id).

    Returns
    -------
    str
        The layer id to give martin.
    """
    if not data.endswith((".geoparquet", ".parquet")):
        return fallback
    basename = data.split("://", 1)[-1].rpartition("/")[2]
    stem = basename.removesuffix(".geoparquet").removesuffix(".parquet")
    if not stem or any(char in stem for char in "*?["):
        return fallback
    return stem


def _martin_store_options(store_options: dict | None, data: str) -> dict[str, Any]:
    """A provider's ``store_options`` as martin's per-source object-store keys.

    ``store_options`` are written in DuckDB's secret vocabulary; martin, like
    obstore, takes object_store's (``virtual_hosted_style_request``, an
    ``endpoint`` URL that, virtual-hosted, names the bucket) and turns them
    back into the DuckDB S3 secret it creates on each connection. So the
    translation the obstore reader already uses is reused here. ``scope``
    is dropped: martin's secret lives on the source's own connections and
    needs none, and an unknown key would only be warned about. A plain
    ``http`` endpoint is refused by martin unless ``allow_http`` says so.

    Parameters
    ----------
    store_options : dict | None
        The provider's ``store_options``, if any.
    data : str
        The provider's ``data``, whose bucket a virtual-hosted endpoint names.

    Returns
    -------
    dict
        Keys to merge into the martin ``duckdb`` source entry; empty for a
        local file or a provider without ``store_options``.
    """
    if not store_options or "://" not in data:
        return {}
    options = _for_obstore({k: v for k, v in store_options.items() if k != "scope"}, data)
    if str(options.get("endpoint", "")).startswith("http://"):
        options["allow_http"] = True
    return options


def _martin_config_from_pygeoapi(pygeoapi_config: dict) -> dict[str, Any]:
    """Derive a martin-py config from an already-loaded pygeoapi config.

    One pygeoapi resource maps to (at most) one martin-py source, keyed
    by the resource id — the same id then names it in
    ``/martin-wrapper/{source_ids}/{z}/{x}/{y}`` and in pygeoapi's own
    ``/collections/{resource_id}/...``, so the two can be benchmarked
    tile-for-tile against the same underlying data. Only providers this
    ``martin-py`` build (features: ``geojson``, ``pmtiles``,
    ``unstable-duckdb``) can actually open are translated:

    - ``GeoJSON`` (or any provider whose ``data`` ends in ``.geojson``/
      ``.json``) -> a ``geojson`` source.
    - ``data`` ending in ``.pmtiles`` -> a ``pmtiles`` source (no
      built-in pygeoapi provider is named for it, so this is
      extension-only detection).
    - the project's GeoParquet provider (or upstream ``Parquet``, or any
      provider whose ``data`` ends in ``.parquet``) -> a ``duckdb``
      source, carrying over ``geometry_column`` and a best-effort SRID.

    A resource whose provider ``data`` is not a string (e.g. an inline
    OGR connection dict), or whose provider is anything else (CSV,
    OGR/GPKG, PostgreSQL, MVT-*, rasterio, xarray, ...), contributes no
    source — there is no one-to-one martin-py equivalent for it here.

    Parameters
    ----------
    pygeoapi_config : dict
        A parsed pygeoapi configuration document (``resources`` mapping
        included), such as the one ``load_config_source`` returns.

    Returns
    -------
    dict
        A martin-py config, ready for ``yaml.safe_dump`` or direct use
        via a temp file with :func:`build_martin_wrapper_app`. Only the
        top-level keys (``geojson``, ``pmtiles``, ``duckdb``) that
        actually gained a source are present; an empty dict means no
        resource had a provider this build of martin-py can manage.
    """
    geojson_sources: dict[str, str] = {}
    pmtiles_sources: dict[str, str] = {}
    duckdb_sources: list[dict[str, Any]] = []

    for resource_id, resource in (pygeoapi_config.get("resources") or {}).items():
        for provider in resource.get("providers") or []:
            data = provider.get("data")
            if not isinstance(data, str):
                continue
            name = provider.get("name")
            if name in _GEOJSON_PROVIDER_NAMES or data.endswith((".geojson", ".json")):
                geojson_sources[resource_id] = data
            elif data.endswith(".pmtiles"):
                pmtiles_sources[resource_id] = data
            elif name in _DUCKDB_PROVIDER_NAMES or data.endswith(".parquet"):
                duckdb_sources.append(
                    {
                        "geoparquet": _geoparquet_location(data),
                        "layer_id": _layer_id_from_data(data, resource_id),
                        "geometry_column": provider.get("geometry_column", "geom"),
                        "srid": _srid_from_storage_crs(provider),
                        **_martin_store_options(provider.get("store_options"), data),
                    }
                )

    martin_config: dict[str, Any] = {}
    if geojson_sources:
        martin_config["geojson"] = {"sources": geojson_sources}
    if pmtiles_sources:
        martin_config["pmtiles"] = {"sources": pmtiles_sources}
    if duckdb_sources:
        martin_config["duckdb"] = {"sources": duckdb_sources}
    return martin_config


def build_martin_wrapper_app_from_pygeoapi(pygeoapi_config: dict) -> Starlette | None:
    """Build the wrapper sub-app straight from a pygeoapi config (ADR-0003).

    `TileServer` only takes a config **path** — there is no dict-based
    constructor — so the config `_martin_config_from_pygeoapi` derives is
    written to a throwaway temp file just to hand it across that one
    call, then removed again immediately: `TileServer.__init__` resolves
    every source eagerly (opens each file, reads its schema), so by the
    time `build_martin_wrapper_app` returns, nothing ever reads the file
    back from disk again. This is the same pattern
    `main._write_openapi_artifact` uses in reverse — there an in-memory
    dict is persisted for external readers; here it exists only to cross
    one call boundary that insists on a path.

    Parameters
    ----------
    pygeoapi_config : dict
        A parsed pygeoapi configuration document — the very one already
        loaded to build the pygeoapi sub-app, so no second file has to
        be kept in sync with it by hand.

    Returns
    -------
    Starlette | None
        The wrapper sub-app, or `None` when no resource had a provider
        this martin-py build can manage — nothing to mount.
    """
    martin_config = _martin_config_from_pygeoapi(pygeoapi_config)
    if not martin_config:
        return None

    fd, tmp_path = tempfile.mkstemp(prefix="martin-wrapper-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(martin_config, f)
        return build_martin_wrapper_app(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def build_martin_wrapper_app(config_path: str) -> Starlette:
    """Build the `/{source_ids}/{z}/{x}/{y}` wrapper sub-app.

    The `TileServer` is built once here, eagerly, rather than lazily on
    the first request: a fair benchmark should not have its first sample
    pay for source resolution the rest never do.

    Parameters
    ----------
    config_path : str
        Path to a Martin config file (the same format the `martin`
        server itself reads), naming the tile sources to resolve.

    Returns
    -------
    Starlette
        A sub-app to mount at `/martin-wrapper`. Raises whatever
        `TileServer` raises if `config_path` is missing or invalid —
        an operator who explicitly configured this wants to know, not
        have it silently skipped.
    """
    server = TileServer(config_path)
    logger.info(f"martin-wrapper: loaded {len(server.list_sources())} source(s) from {config_path}")

    async def get_tile(request: Request) -> Response:
        source_ids = request.path_params["source_ids"]
        z = request.path_params["z"]
        x = request.path_params["x"]
        y = request.path_params["y"]
        try:
            # A tile can take seconds (a remote GeoParquet scan); martin-py
            # releases the GIL, so a worker thread keeps the event loop free.
            data, content_type, content_encoding = await run_in_threadpool(
                server.get_tile, source_ids, z, x, y, query=request.url.query or None
            )
        except Exception as e:
            logger.warning(f"martin-wrapper: tile fetch failed for {source_ids}/{z}/{x}/{y}: {e}")
            return JSONResponse({"code": "NotFound", "description": str(e)}, status_code=404)
        headers = {"Content-Encoding": content_encoding} if content_encoding else {}
        return Response(content=data, media_type=content_type, headers=headers)

    return Starlette(
        routes=[Route("/{source_ids}/{z:int}/{x:int}/{y:int}", get_tile)],
    )
