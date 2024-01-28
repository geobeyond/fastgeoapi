"""OAuth2 provider module."""
import re
from abc import ABC
from abc import abstractmethod
from typing import List
from typing import Optional

from app.auth.auth_interface import AuthInterface
from starlette.requests import Request


class Injectable(ABC):
    """Define interface for injectables."""

    def __init__(
        self, key: str, skip_endpoints: Optional[List[str]] = []  # noqa B006
    ) -> None:
        """Set properties initialization for injectables."""
        self.key = key
        self.skip_endpoints = [
            re.compile(skip) for skip in skip_endpoints  # type:ignore
        ]

    @abstractmethod
    async def extract(self, request: Request) -> List:
        """Extract the token from the request."""
        pass


class Oauth2Provider:
    """OAuth2 middleware."""

    def __init__(
        self,
        authentication: [AuthInterface, List[AuthInterface]],  # type:ignore
        injectables: Optional[List[Injectable]] = None,
        accepted_methods: Optional[List[str]] = [  # noqa B006
            "id_token",
            "access_token",
        ],
    ) -> None:
        """Handle configuration container for the OAuth2 middleware.  # noqa D405

        PARAMETERS
        ----------
        authentication: [AuthInterface, List[AuthInterface]]
            Authentication Implementations to be used for the
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
        self.accepted_methods = accepted_methods
