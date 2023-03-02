"""Openapi middleware module."""
from typing import Any
from typing import Dict

from openapi_schema_pydantic import OpenAPI
from openapi_schema_pydantic import SecurityScheme
from starlette.datastructures import Headers
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp
from starlette.types import Message
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send


routes_with_middleware = ["/openapi"]
queryparams_with_middleware = ["f=json"]


class OpenapiSecurityMiddleware:
    """Openapi security middleware."""

    def __init__(self, app: ASGIApp, security_scheme: SecurityScheme):
        """Initialize the Openapi security middleware."""
        self.app = app
        self.security_scheme = security_scheme

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        """Call the Openapi middleware."""
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        pygeoapi_path = scope["path"]
        pygeoapi_query_params = scope["query_string"].decode()
        if pygeoapi_path not in routes_with_middleware:
            return await self.app(scope, receive, send)
        else:
            if pygeoapi_query_params in queryparams_with_middleware:
                openapi_responder = OpenAPIResponder(self.app, self.security_scheme)
                await openapi_responder(scope, receive, send)
                return
            await self.app(scope, receive, send)


class OpenAPIResponder:
    """OpenAPI responder interface."""

    def __init__(
        self,
        app: ASGIApp,
        security_scheme: SecurityScheme,
        headers: Dict[Any, Any] = {},  # noqa: B006
    ):
        """Initialize the OpenAPI responder class."""
        self.app = app
        self.initial_message = {}  # type: Message
        self.security_scheme = security_scheme
        self.headers = headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Call the Openapi responder interface."""
        self.send = send
        await self.app(scope, receive, self.send_with_security)

    async def send_with_security(self, message: Message) -> None:  # noqa: C901
        """Apply security using supported schemes."""
        message_type = message["type"]
        if message_type == "http.response.start":
            # Don't send the initial message until we've determined how to
            # modify the outgoing headers correctly.
            self.initial_message = message
            headers = Headers(raw=self.initial_message["headers"])
            headers_dict = dict(headers.items())
            content_type = headers_dict.get("content-type")
            if "application/vnd.oai.openapi+json" not in str(content_type):
                raise ValueError(f"Unsupported content type: {content_type}")
            self.headers.update(headers_dict)
        if message_type == "http.response.body":
            initial_body = message.get("body", b"").decode()
            openapi = OpenAPI.parse_raw(initial_body)
            if self.security_scheme.type == "apiKey":
                security_schemes = {
                    "securitySchemes": {
                        "PygeoApiKey": self.security_scheme.dict(
                            by_alias=True, exclude_none=True
                        )
                    }
                }
                body = openapi.dict(by_alias=True, exclude_none=True)
                components = body.get("components")
                if components:
                    components.update(security_schemes)
                body["components"] = components
                paths = openapi.paths
                if paths:
                    secured_paths = {}
                    for key, value in paths.items():
                        if value.get:
                            value.get.security = [{"PygeoApiKey": []}]
                        if value.post:
                            value.post.security = [{"PygeoApiKey": []}]
                        secured_paths.update({key: value})
                if secured_paths:
                    body["paths"] = secured_paths
                binary_body = (
                    OpenAPI.parse_obj(body)
                    .json(by_alias=True, exclude_none=True, indent=2)
                    .encode()
                )
                headers = MutableHeaders(raw=self.initial_message["headers"])
                headers["Content-Length"] = str(len(binary_body))
                message["body"] = binary_body
                await self.send(self.initial_message)
                await self.send(message)
