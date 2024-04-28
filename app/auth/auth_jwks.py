"""Auth JWKS module."""

import typing
from dataclasses import dataclass
from dataclasses import field

import httpx
from authlib.jose import JsonWebKey
from authlib.jose import JsonWebToken
from authlib.jose import JWTClaims
from authlib.jose import KeySet
from authlib.jose import errors
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.auth.auth_interface import AuthInterface
from app.auth.exceptions import Oauth2Error
from app.auth.models import OAuth2Claim
from app.config.logging import create_logger

# from cachetools import cached
# from cachetools import TTLCache


logger = create_logger("app.auth.auth_jwks")


@dataclass
class JWKSConfig:
    """JWKS configuration instance."""

    jwks_uri: str = field(default="")


class JWKSAuthentication(AuthInterface):
    """JWKS authentication instance."""

    def __init__(self, config: JWKSConfig) -> None:
        """Initialize the authentication."""
        self.config = config

    # @cached(TTLCache(maxsize=1, ttl=3600))
    async def get_jwks(self) -> KeySet:
        """Get cached or new JWKS."""
        url = self.config.jwks_uri
        logger.info(f"Fetching JSON Web Key Set from {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            return JsonWebKey.import_key_set(response.json())

    async def decode_token(
        self,
        token: str,
    ) -> JWTClaims:
        """Validate and decode JWT."""
        try:
            jwks = await self.get_jwks()
            logger.debug(f"JSON Key Set: {jwks.as_json()}")
            alg = jwks.as_dict()["keys"][0]["alg"]
            claims = JsonWebToken([alg]).decode(
                s=token,
                key=jwks,
                # claim_options={
                #     # Example of validating audience to match expected value
                #     # "aud": {"essential": True, "values": [APP_CLIENT_ID]}
                # }
            )
            logger.debug(f"Decoded claims: {OAuth2Claim(**claims)}")
            if "client_id" in claims:
                # Insert Cognito's `client_id` into `aud` claim if `aud` claim is unset
                claims.setdefault("aud", claims["client_id"])
            claims.validate()
        except errors.ExpiredTokenError:
            logger.error("Unable to validate an expired token")
            raise Oauth2Error("Unable to validate an expired token")  # noqa
        except errors.JoseError:
            logger.error("Unable to decode token")
            raise Oauth2Error("Unable to decode token")  # noqa

        return claims

    async def authenticate(
        self,
        request: Request,
        accepted_methods: typing.Optional[typing.List[str]] = ["access_token"],  # noqa
    ) -> typing.Union[RedirectResponse, typing.Dict]:
        """Authenticate the caller with the incoming request."""
        bearer = request.headers.get("Authorization")
        if not bearer:
            logger.exception("Unable to get a token")
            raise Oauth2Error("Auth token not found")
        access_token = bearer.replace("Bearer ", "")
        try:
            claims = await self.decode_token(access_token)
            if not claims:
                pass
            return claims
        except Exception:
            raise Oauth2Error("Authentication error")  # noqa
