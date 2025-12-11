"""Starlette application override module."""

import asyncio
from collections.abc import Callable
from typing import Any

import pygeoapi.api.processes as processes_api
from pygeoapi.api import APIRequest
from pygeoapi.starlette_app import api_ as geoapi
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response


def call_api_threadsafe(loop: asyncio.AbstractEventLoop, api_call: Callable, *args) -> tuple:
    """Call api in a safe thread.

    The api call needs a running loop. This method is meant to be called
    from a thread that has no loop running.

    :param loop: The loop to use.
    :param api_call: The API method to call.
    :param args: Arguments to pass to the API method.
    :returns: The api call result tuple.
    """
    asyncio.set_event_loop(loop)
    return api_call(*args)


async def get_response(
    api_call,
    *args,
) -> Any:
    """Creates a Starlette Response object and updates matching headers.

    Runs the core api handler in a separate thread in order to avoid
    blocking the main event loop.

    :param result: The result of the API call.
                   This should be a tuple of (headers, status, content).

    :returns: A Response instance.
    """
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, call_api_threadsafe, loop, api_call, *args)

    headers, status, content = result
    if headers["Content-Type"] == "text/html":
        response: Any = HTMLResponse(content=content, status_code=status)
    else:
        if isinstance(content, dict):
            response = JSONResponse(content, status_code=status)
        else:
            response = Response(content, status_code=status)

    if headers is not None:
        response.headers.update(headers)
    return response


async def patched_get_job_result(request: Request, job_id=None):
    """OGC API - Processes job result endpoint.

    :param request: Starlette Request instance
    :param job_id: job identifier

    :returns: HTTP response
    """
    if "job_id" in request.path_params:
        job_id = request.path_params["job_id"]

    # Convert Starlette Request to APIRequest
    api_request = await APIRequest.from_starlette(request, geoapi.locales)

    response = await get_response(processes_api.get_job_result, geoapi, api_request, job_id)

    from app.pygeoapi.api.processes import patch_response

    patched_response = patch_response(response=response)

    return patched_response
