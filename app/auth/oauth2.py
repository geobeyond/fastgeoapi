"""OAuth2 provider module."""

import re
from abc import ABC, abstractmethod

from starlette.requests import Request

from app.auth.auth_interface import AuthInterface


class Injectable(ABC):
    """Define interface for injectables."""

    def __init__(
        self,
        key: str,
        skip_endpoints: list[str] | None = None,
    ) -> None:
        """Set properties initialization for injectables."""
        self.key = key
        self.skip_endpoints = [re.compile(skip) for skip in (skip_endpoints or [])]

    @abstractmethod
    async def extract(self, request: Request) -> list:
        """Extract the token from the request."""
        pass


class Oauth2Provider:
    """OAuth2 middleware."""

    def __init__(
        self,
        authentication: AuthInterface | list[AuthInterface],
        injectables: list[Injectable] | None = None,
        accepted_methods: list[str] | None = None,
    ) -> None:
        """Handle configuration container for the OAuth2 middleware.  # noqa D405

        Parameters
        ----------
        authentication: [AuthInterface, List[AuthInterface]]
            Authentication implementations to be used for the
            request authentication.
        injectables: List[Injectable], default=None
            List of injectables to be used to add information to the
            request payload.
        accepted_methods: List[str], default=["id_token", "access_token"]
            List of accepted authentication methods.
        """
        if not isinstance(authentication, list):
            authentication = [authentication]
        self.authentication = authentication
        self.injectables = injectables
        self.accepted_methods = accepted_methods or ["id_token", "access_token"]
