"""Programmatic construction of the pygeoapi sub-app.

Replaces the import of ``pygeoapi.starlette_app`` (module globals built
from env+file at import time) with explicit construction from dicts.
The execute shim and the route table are adapted from
``pygeoapi/starlette_app.py`` (MIT); the parity test
``tests/test_pygeoapi_route_parity.py`` keeps them aligned to upstream.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from http import HTTPStatus
from pathlib import Path

import pygeoapi
import pygeoapi.api as core_api
import pygeoapi.api.coverages as coverages_api
import pygeoapi.api.environmental_data_retrieval as edr_api
import pygeoapi.api.itemtypes as itemtypes_api
import pygeoapi.api.maps as maps_api
import pygeoapi.api.processes as processes_api
import pygeoapi.api.stac as stac_api
import pygeoapi.api.tiles as tiles_api
from pygeoapi.api import API, APIRequest, apply_gzip
from pygeoapi.openapi import get_oas
from pygeoapi.util import get_api_rules
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.pygeoapi.api import patch_validate_datetime_overflow
from app.pygeoapi.openapi import fix_queryables_response_schema
from app.pygeoapi.plugin import invalidate_plugin_cache, patch_load_plugin

# The fastgeoapi runtime patches apply once, at factory import: every
# sub-app built afterwards inherits them (the same moment the old
# app/pygeoapi/starlette_app.py used to apply them).
patch_validate_datetime_overflow()
patch_load_plugin()


# Documented defaults from pygeoapi's own config schema
# (resources/schemas/config/pygeoapi-config-0.x.yml): both limit keys
# default to 10. The schema requires neither, but the items HTML
# template dereferences `config['server']['limits']['default_items']`
# without a fallback — while pygeoapi's Python code reads the same
# values with `.get('limits', {})`. A tenant config can therefore be
# schema-valid, serve JSON happily, and 500 in a browser. Filling the
# documented defaults keeps "valid config" and "working server" the
# same statement.
_LIMIT_DEFAULTS = {"default_items": 10, "max_items": 10}


def normalize_config(config: dict) -> dict:
    """Fill the optional config keys the runtime assumes are present.

    Mutates and returns the given dict: callers (including the reload
    path) share one config object, and pygeoapi copies it internally
    anyway. Only absent keys are filled — a tenant's own values stay.
    """
    limits = config.setdefault("server", {}).setdefault("limits", {})
    for key, value in _LIMIT_DEFAULTS.items():
        limits.setdefault(key, value)
    return config


def build_openapi(config: dict) -> dict:
    """Generate the OpenAPI in memory, with the fastgeoapi fixes at the source."""
    doc = get_oas(normalize_config(config))
    fix_queryables_response_schema(doc)
    return doc


def build_api(config: dict, openapi: dict) -> API:
    """pygeoapi's API instance, with no file nor env var in between.

    Also drops pygeoapi's translated-config cache. ``l10n.translate_struct``
    memoises the config it hands to the HTML templates in a MODULE-level
    dict keyed by locale, so after a reload swap the browser would keep
    seeing config-derived values (the site title, the item-limit options)
    from the previous config while JSON already served the new one. A new
    API instance means a new config, so the cache must go with it.
    """
    from pygeoapi import l10n

    l10n._cfg_cache.clear()
    # Cached plugin instances were built from the previous config: a
    # reload must not keep serving providers that point at data the new
    # config no longer describes.
    invalidate_plugin_cache()
    return API(normalize_config(config), openapi)


def _call_threadsafe(loop: asyncio.AbstractEventLoop, api_call: Callable, *args) -> tuple:
    asyncio.set_event_loop(loop)
    return api_call(*args)


def _to_response(headers: dict, status: int, content) -> Response:
    if headers["Content-Type"] == "text/html":
        response: Response = HTMLResponse(content=content, status_code=status)
    elif isinstance(content, dict):
        response = JSONResponse(content, status_code=status)
    else:
        response = Response(content, status_code=status)
    if headers is not None:
        response.headers.update(headers)
    return response


async def execute(
    api: API,
    api_function: Callable,
    request: Request,
    *args,
    skip_valid_check: bool = False,
) -> Response:
    """Adaptation of ``execute_from_starlette`` with an explicit API instance."""
    api_request = await APIRequest.from_starlette(request, api.locales)
    if not skip_valid_check and not api_request.is_valid():
        headers, status, content = api.get_format_exception(api_request)
    else:
        loop = asyncio.get_running_loop()
        headers, status, content = await loop.run_in_executor(
            None, _call_threadsafe, loop, api_function, api, api_request, *args
        )
        if status != HTTPStatus.NO_CONTENT:
            content = apply_gzip(headers, content)
    return _to_response(headers, status, content)


def _path_param(request: Request, name: str):
    return request.path_params.get(name)


def build_routes(api: API, specs: frozenset[str] | None = None) -> list[Route]:
    """The route table, closed over the ``api`` instance.

    Adapted 1:1 from ``pygeoapi/starlette_app.py`` (admin excluded: in
    its place fastgeoapi has the reload webhook). Every entry is tagged
    with its spec group (ADR-0005): ``specs=None`` returns the COMPLETE
    table — the coverage contract the parity test checks against
    upstream — while the sub-app mounts only the active groups.
    """

    async def landing_page(request: Request) -> Response:
        return await execute(api, core_api.landing_page, request)

    async def openapi_(request: Request) -> Response:
        return await execute(api, core_api.openapi_, request)

    async def asyncapi_(request: Request) -> Response:
        return await execute(api, core_api.asyncapi_, request)

    async def conformance(request: Request) -> Response:
        # fastgeoapi patch: filter the classes by the configured providers.
        from app.pygeoapi.api.conformance import conformance as conformance_fn

        return await execute(api, conformance_fn, request)

    async def tilematrixset(request: Request) -> Response:
        return await execute(
            api,
            tiles_api.tilematrixset,
            request,
            _path_param(request, "tileMatrixSetId"),
        )

    async def tilematrixsets(request: Request) -> Response:
        return await execute(api, tiles_api.tilematrixsets, request)

    async def collection_schema(request: Request) -> Response:
        return await execute(
            api,
            core_api.get_collection_schema,
            request,
            _path_param(request, "collection_id"),
        )

    async def collection_queryables(request: Request) -> Response:
        return await execute(
            api,
            itemtypes_api.get_collection_queryables,
            request,
            _path_param(request, "collection_id"),
        )

    async def collection_tiles(request: Request) -> Response:
        return await execute(
            api,
            tiles_api.get_collection_tiles,
            request,
            _path_param(request, "collection_id"),
        )

    async def collection_tiles_metadata(request: Request) -> Response:
        return await execute(
            api,
            tiles_api.get_collection_tiles_metadata,
            request,
            _path_param(request, "collection_id"),
            _path_param(request, "tileMatrixSetId"),
            skip_valid_check=True,
        )

    async def collection_items_tiles(request: Request) -> Response:
        return await execute(
            api,
            tiles_api.get_collection_tiles_data,
            request,
            _path_param(request, "collection_id"),
            _path_param(request, "tileMatrixSetId"),
            _path_param(request, "tile_matrix"),
            _path_param(request, "tileRow"),
            _path_param(request, "tileCol"),
            skip_valid_check=True,
        )

    async def collection_items(request: Request) -> Response:
        collection_id = _path_param(request, "collection_id")
        item_id = _path_param(request, "item_id")
        if item_id is None:
            if request.method == "POST":
                if request.headers.get("content-type") == "application/geo+json":
                    return await execute(
                        api,
                        itemtypes_api.manage_collection_item,
                        request,
                        "create",
                        collection_id,
                        skip_valid_check=True,
                    )
                return await execute(
                    api,
                    itemtypes_api.get_collection_items,
                    request,
                    collection_id,
                    skip_valid_check=True,
                )
            if request.method == "OPTIONS":
                return await execute(
                    api,
                    itemtypes_api.manage_collection_item,
                    request,
                    "options",
                    collection_id,
                    skip_valid_check=True,
                )
            return await execute(
                api,
                itemtypes_api.get_collection_items,
                request,
                collection_id,
                skip_valid_check=True,
            )
        if request.method in ("DELETE", "PUT", "OPTIONS"):
            action = {
                "DELETE": "delete",
                "PUT": "update",
                "OPTIONS": "options",
            }[request.method]
            return await execute(
                api,
                itemtypes_api.manage_collection_item,
                request,
                action,
                collection_id,
                item_id,
                skip_valid_check=True,
            )
        return await execute(
            api,
            itemtypes_api.get_collection_item,
            request,
            collection_id,
            item_id,
        )

    async def collection_coverage(request: Request) -> Response:
        return await execute(
            api,
            coverages_api.get_collection_coverage,
            request,
            _path_param(request, "collection_id"),
            skip_valid_check=True,
        )

    async def collection_map(request: Request) -> Response:
        return await execute(
            api,
            maps_api.get_collection_map,
            request,
            _path_param(request, "collection_id"),
            _path_param(request, "style_id"),
        )

    async def get_processes(request: Request) -> Response:
        return await execute(
            api,
            processes_api.describe_processes,
            request,
            _path_param(request, "process_id"),
        )

    async def get_jobs(request: Request) -> Response:
        job_id = _path_param(request, "job_id")
        if job_id is None:
            return await execute(api, processes_api.get_jobs, request)
        if request.method == "DELETE":
            return await execute(api, processes_api.delete_job, request, job_id)
        return await execute(api, processes_api.get_jobs, request, job_id)

    async def execute_process_jobs(request: Request) -> Response:
        return await execute(
            api,
            processes_api.execute_process,
            request,
            _path_param(request, "process_id"),
        )

    async def get_job_result(request: Request) -> Response:
        # fastgeoapi patch: job response corrected downstream.
        from app.pygeoapi.api.processes import patch_response

        response = await execute(
            api,
            processes_api.get_job_result,
            request,
            _path_param(request, "job_id"),
        )
        return patch_response(response=response)

    async def edr_query(request: Request) -> Response:
        collection_id = _path_param(request, "collection_id")
        instance_id = _path_param(request, "instance_id")
        if collection_id and "/instances/" in collection_id:
            collection_id, _, instance_id = collection_id.partition("/instances/")
        if request.url.path.endswith("instances") or (
            instance_id is not None and request.url.path.endswith(instance_id)
        ):
            return await execute(
                api,
                edr_api.get_collection_edr_instances,
                request,
                collection_id,
                instance_id,
            )
        location_id = _path_param(request, "location_id")
        query_type = "locations" if location_id is not None else request["path"].split("/")[-1]
        return await execute(
            api,
            edr_api.get_collection_edr_query,
            request,
            collection_id,
            instance_id,
            query_type,
            location_id,
            skip_valid_check=True,
        )

    async def collections(request: Request) -> Response:
        return await execute(
            api,
            core_api.describe_collections,
            request,
            _path_param(request, "collection_id"),
        )

    async def stac_catalog_root(request: Request) -> Response:
        return await execute(api, stac_api.get_stac_root, request)

    async def stac_catalog_path(request: Request) -> Response:
        return await execute(api, stac_api.get_stac_path, request, _path_param(request, "path"))

    async def stac_landing_page(request: Request) -> Response:
        return await execute(api, stac_api.landing_page, request)

    async def stac_search(request: Request) -> Response:
        return await execute(api, stac_api.search, request)

    table: list[tuple[str, Route]] = [
        ("core", Route("/", landing_page)),
        ("core", Route("/openapi", openapi_)),
        ("core", Route("/asyncapi", asyncapi_)),
        ("core", Route("/conformance", conformance)),
        ("tiles", Route("/TileMatrixSets/{tileMatrixSetId}", tilematrixset)),
        ("tiles", Route("/TileMatrixSets", tilematrixsets)),
        (
            "core",
            Route("/collections/{collection_id:path}/schema", collection_schema),
        ),
        (
            "core",
            Route(
                "/collections/{collection_id:path}/queryables",
                collection_queryables,
            ),
        ),
        (
            "tiles",
            Route("/collections/{collection_id:path}/tiles", collection_tiles),
        ),
        (
            "tiles",
            Route(
                "/collections/{collection_id:path}/tiles/{tileMatrixSetId}",
                collection_tiles_metadata,
            ),
        ),
        (
            "tiles",
            Route(
                "/collections/{collection_id:path}/tiles/{tileMatrixSetId}/metadata",
                collection_tiles_metadata,
            ),
        ),
        (
            "tiles",
            Route(
                "/collections/{collection_id:path}/tiles/{tileMatrixSetId}/{tile_matrix}/{tileRow}/{tileCol}",
                collection_items_tiles,
            ),
        ),
        (
            "features",
            Route(
                "/collections/{collection_id:path}/items",
                collection_items,
                methods=["GET", "POST", "OPTIONS"],
            ),
        ),
        (
            "features",
            Route(
                "/collections/{collection_id:path}/items/{item_id:path}",
                collection_items,
                methods=["GET", "PUT", "DELETE", "OPTIONS"],
            ),
        ),
        (
            "coverages",
            Route(
                "/collections/{collection_id:path}/coverage",
                collection_coverage,
            ),
        ),
        (
            "maps",
            Route("/collections/{collection_id:path}/map", collection_map),
        ),
        (
            "maps",
            Route(
                "/collections/{collection_id:path}/styles/{style_id:path}/map",
                collection_map,
            ),
        ),
        ("processes", Route("/processes", get_processes)),
        ("processes", Route("/processes/{process_id}", get_processes)),
        ("processes", Route("/jobs", get_jobs)),
        (
            "processes",
            Route("/jobs/{job_id}", get_jobs, methods=["GET", "DELETE"]),
        ),
        (
            "processes",
            Route(
                "/processes/{process_id}/execution",
                execute_process_jobs,
                methods=["POST"],
            ),
        ),
        ("processes", Route("/jobs/{job_id}/results", get_job_result)),
        ("edr", Route("/collections/{collection_id:path}/position", edr_query)),
        ("edr", Route("/collections/{collection_id:path}/area", edr_query)),
        ("edr", Route("/collections/{collection_id:path}/cube", edr_query)),
        ("edr", Route("/collections/{collection_id:path}/radius", edr_query)),
        (
            "edr",
            Route("/collections/{collection_id:path}/trajectory", edr_query),
        ),
        ("edr", Route("/collections/{collection_id:path}/corridor", edr_query)),
        (
            "edr",
            Route("/collections/{collection_id:path}/locations", edr_query),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/locations/{location_id}",
                edr_query,
            ),
        ),
        (
            "edr",
            Route("/collections/{collection_id:path}/instances", edr_query),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}",
                edr_query,
            ),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}/position",
                edr_query,
            ),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}/area",
                edr_query,
            ),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}/cube",
                edr_query,
            ),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}/radius",
                edr_query,
            ),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}/trajectory",
                edr_query,
            ),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}/corridor",
                edr_query,
            ),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}/locations",
                edr_query,
            ),
        ),
        (
            "edr",
            Route(
                "/collections/{collection_id:path}/instances/{instance_id}/locations/{location_id}",
                edr_query,
            ),
        ),
        ("core", Route("/collections", collections)),
        ("core", Route("/collections/{collection_id:path}", collections)),
        ("stac", Route("/stac", stac_catalog_root)),
        ("stac", Route("/stac/{path:path}", stac_catalog_path)),
        ("stac", Route("/stac-api", stac_landing_page)),
        (
            "stac",
            Route("/stac-api/search", stac_search, methods=["GET", "POST"]),
        ),
    ]
    if specs is None:
        return [route for _, route in table]
    return [route for spec, route in table if spec in specs]


def build_pygeoapi_subapp(config: dict, openapi: dict) -> Starlette:
    """Complete Starlette sub-app, same shape as the former APP import.

    Mounts only the spec groups the config activates (ADR-0005): the
    reload webhook rebuilds the sub-app, so the mounted set follows
    every config update.
    """
    from app.pygeoapi.registry import active_specs

    api = build_api(config, openapi)
    static_dir = Path(pygeoapi.__file__).parent / "static"
    try:
        static_dir = Path(config["server"]["templates"]["static"])
    except KeyError:
        pass
    url_prefix = get_api_rules(config).get_url_prefix("starlette")
    return Starlette(
        routes=[
            Mount("/static", StaticFiles(directory=static_dir)),
            Mount(
                url_prefix or "/",
                routes=build_routes(api, specs=active_specs(config)),
            ),
        ],
    )
