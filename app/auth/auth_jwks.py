import typing
from dataclasses import dataclass
from dataclasses import field

import httpx
from app.auth.auth_interface import AuthInterface
from app.auth.exceptions import OIDCException
from app.config.logging import create_logger
from authlib.jose import errors
from authlib.jose import JsonWebKey
from authlib.jose import JsonWebToken
from authlib.jose import JWTClaims
from authlib.jose import KeySet
from cachetools import cached
from cachetools import TTLCache
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse


logger = create_logger("app.auth.auth_jwks")


@dataclass
class JWKSConfig:
    jwks_uri: str = field(default="")


class JWKSAuthentication(AuthInterface):
    def __init__(self, config: JWKSConfig) -> None:
        self.config = config

    # @cached(TTLCache(maxsize=1, ttl=3600))
    async def get_jwks(self) -> KeySet:
        """
        Get cached or new JWKS.
        """
        url = self.config.jwks_uri
        logger.info(f"Fetching JSON Web Key Set from {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            return JsonWebKey.import_key_set(response.json())

    async def decode_token(
        self,
        token: str,
    ) -> JWTClaims:
        """
        Validate & decode JWT.
        """
        try:
            jwks = await self.get_jwks()
            claims = JsonWebToken(["RS256"]).decode(
                s=token,
                key=jwks,
                # claim_options={
                #     # Example of validating audience to match expected value
                #     # "aud": {"essential": True, "values": [APP_CLIENT_ID]}
                # }
            )
            if "client_id" in claims:
                # Insert Cognito's `client_id` into `aud` claim if `aud` claim is unset
                claims.setdefault("aud", claims["client_id"])
            claims.validate()
        except errors.ExpiredTokenError:
            logger.error("Unable to validate an expired token")
            raise OIDCException("Unable to validate an expired token")
        except errors.JoseError:
            logger.error("Unable to decode token")
            raise OIDCException("Unable to decode token")

        return claims

    async def authenticate(
        self,
        request: Request,
        accepted_methods: typing.Optional[typing.List[str]] = ["access_token"],
    ) -> typing.Union[RedirectResponse, typing.Dict]:
        bearer = request.headers.get("Authorization")
        if not bearer:
            logger.exception("Unable to get a token")
            raise OIDCException("Auth token not found")
        access_token = bearer.replace("Bearer ", "")
        try:
            claims = await self.decode_token(access_token)
            if not claims:
                pass
            return claims
        except:
            raise OIDCException("Authentication error")
