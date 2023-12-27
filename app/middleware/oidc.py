import asyncio
import logging
import re
from typing import List
from typing import Optional

from app.auth.exceptions import AuthenticationException
from app.auth.oidc import OIDCProvider
from app.config.logging import create_logger
from fastapi.responses import JSONResponse
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

try:
    Pattern = re.Pattern
except AttributeError:
    # Python3.6 does not contain re.Pattern
    Pattern = None


logger = create_logger("app.middleware.oidc")


def should_skip_endpoint(endpoint: str, skip_endpoints: List[Pattern]) -> bool:
    for skip in skip_endpoints:
        if skip.match(endpoint):
            return True
    return False


class OwnReceive:
    """
    This class is required in order to access the request
    body multiple times.
    """

    def __init__(self, receive: Receive):
        self.receive = receive
        self.data = None

    async def __call__(self):
        if self.data is None:
            self.data = await self.receive()

        return self.data


class OIDCMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        config: OIDCProvider,
        skip_endpoints: Optional[List[str]] = [
            "/openapi",
            "/openapi.json",
            "/docs",
            "/redoc",
        ],
    ) -> None:
        self.config = config
        self.app = app
        self.skip_endpoints = [re.compile(skip) for skip in skip_endpoints]

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)

        # Small hack to ensure that later we can still receive the body
        # own_receive = OwnReceive(receive)
        request = Request(scope, receive, send)

        if request.method == "OPTIONS":
            return await self.app(scope, receive, send)

        # allow openapi endpoints without authentication
        if should_skip_endpoint(request.url.path, self.skip_endpoints):
            return await self.app(scope, receive, send)

        # authenticate user or get redirect to identity provider
        successful = False
        for auth in self.config.authentication:
            try:
                user_info_or_auth_redirect = auth.authenticate(
                    request, self.config.accepted_methods
                )
                if asyncio.iscoroutine(user_info_or_auth_redirect):
                    user_info_or_auth_redirect = await user_info_or_auth_redirect
                if isinstance(user_info_or_auth_redirect, dict):
                    successful = True
                    break
            except AuthenticationException:
                logger.error("AuthenticationException raised on login")

        # Some authentication flows require a prior redirect to id provider
        if isinstance(user_info_or_auth_redirect, RedirectResponse):
            return await user_info_or_auth_redirect.__call__(scope, receive, send)
        if not successful:
            return await self.get_unauthorized_response(scope, receive, send)

        await self.app(scope, receive, send)

    @staticmethod
    async def get_unauthorized_response(
        scope: Scope, receive: Receive, send: Send
    ) -> None:
        response = JSONResponse(status_code=401, content={"message": "Unauthenticated"})
        return await response(scope, receive, send)
