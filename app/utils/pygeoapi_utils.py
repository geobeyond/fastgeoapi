"""Utilities for pygeoapi module."""

from starlette.routing import Route

from app.pygeoapi.starlette_app import patched_get_job_result


def patch_route(route: Route) -> Route:
    """Patch route behavior."""
    if route.path == "/jobs/{job_id}/results":
        route = Route("/jobs/{job_id}/results", patched_get_job_result)
    return route
