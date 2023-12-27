import re
from abc import ABC
from abc import abstractmethod
from typing import List
from typing import Optional

from app.auth.auth_interface import AuthInterface
from starlette.requests import Request


class Injectable(ABC):
    def __init__(self, key: str, skip_endpoints: Optional[List[str]] = []) -> None:
        self.key = key
        self.skip_endpoints = [re.compile(skip) for skip in skip_endpoints]

    @abstractmethod
    async def extract(self, request: Request) -> List:
        pass


class OIDCProvider:
    def __init__(
        self,
        authentication: [AuthInterface, List[AuthInterface]],
        injectables: Optional[List[Injectable]] = None,
        accepted_methods: Optional[List[str]] = ["id_token", "access_token"],
    ) -> None:
        """
        Configuration container for the OIDCMiddleware.

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
