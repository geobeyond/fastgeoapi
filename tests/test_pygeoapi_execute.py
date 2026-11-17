"""The request context that ``execute`` hands to the pygeoapi call in its thread."""

import json
from contextvars import ContextVar
from pathlib import Path

import pytest
from pygeoapi.util import yaml_load
from starlette.requests import Request

from app.pygeoapi.factory import build_api, build_openapi, execute

request_id: ContextVar[str] = ContextVar("request_id", default="<not set>")


@pytest.fixture(scope="module", name="api")
def create_api():
    with Path("tests/data/pygeoapi-config.yml").open() as config_file:
        config = yaml_load(config_file)
    return build_api(config, build_openapi(config))


def build_request() -> Request:
    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": []}
    return Request(scope, receive)


def read_request_id(api, api_request) -> tuple:
    return {"Content-Type": "application/json"}, 200, {"request_id": request_id.get()}


@pytest.mark.asyncio
async def test_the_call_sees_the_context_variables_of_its_request(api):
    # A middleware sets its variables in the task that serves the request.
    request_id.set("example-request-123")

    response = await execute(api, read_request_id, build_request(), skip_valid_check=True)

    assert json.loads(response.body) == {"request_id": "example-request-123"}
