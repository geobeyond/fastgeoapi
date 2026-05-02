"""Utilities for pygeoapi module."""

from starlette.routing import Route

from app.pygeoapi.starlette_app import (
    patched_conformance,
    patched_get_job_result,
)


def patch_route(route: Route) -> Route:
    """Patch specific pygeoapi routes to add fastgeoapi-specific behavior.

    Currently patched routes:
    - /conformance: Filter conformance classes by configured providers
    - /jobs/{job_id}/results: Custom job result handling
    """
    if route.path == "/conformance":
        return Route("/conformance", patched_conformance)
    if route.path == "/jobs/{job_id}/results":
        return Route("/jobs/{job_id}/results", patched_get_job_result)
    return route
