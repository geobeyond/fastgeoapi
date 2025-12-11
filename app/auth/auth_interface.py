"""Auth interface module."""

from abc import ABC, abstractmethod

from starlette.requests import Request
from starlette.responses import RedirectResponse


class AuthInterface(ABC):
    """Define the interface for the authentication instances.

    The interface provides necessary methods for the OPAMiddleware
    authentication flow. This allows to easily integrate various auth methods.
    """

    @abstractmethod
    async def authenticate(self, request: Request) -> RedirectResponse | dict:
        """Authenticate the incoming request.

        The method returns a dictionary containing the valid and authorized
        users information or a redirect since some flows require calling a
        identity broker beforehand.
        """
        pass
