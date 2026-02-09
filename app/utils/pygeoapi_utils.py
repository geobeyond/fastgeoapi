"""Utilities for pygeoapi module."""

from starlette.routing import Route

from app.pygeoapi.starlette_app import (
    patched_conformance,
    patched_get_job_result,
)


def patch_route(route: Route) -> Route:
    """Patch specific pygeoapi routes to fix bugs or add custom behavior.

    Currently patched routes:
    - /conformance: Fix for global CONFORMANCE_CLASSES list mutation bug
    - /jobs/{job_id}/results: Custom job result handling
    """
    if route.path == "/conformance":
        return Route("/conformance", patched_conformance)
    if route.path == "/jobs/{job_id}/results":
        return Route("/jobs/{job_id}/results", patched_get_job_result)
    return route
