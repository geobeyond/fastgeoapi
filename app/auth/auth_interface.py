"""Auth interface module."""
from abc import ABC
from abc import abstractmethod
from typing import Dict
from typing import Union

from starlette.requests import Request
from starlette.responses import RedirectResponse


class AuthInterface(ABC):
    """Define the interface for the authentication instances.

    The interface provides necessary methods for the OPAMiddleware
    authentication flow. This allows to easily integrate various auth methods.
    """

    @abstractmethod
    async def authenticate(self, request: Request) -> Union[RedirectResponse, Dict]:
        """Authenticate the incoming request.

        The method returns a dictionary containing the valid and authorized
        users information or a redirect since some flows require calling a
        identity broker beforehand.
        """
        pass
