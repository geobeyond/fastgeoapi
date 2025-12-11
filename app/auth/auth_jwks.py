"""Auth JWKS module."""

import typing
from dataclasses import dataclass, field

import httpx
from authlib.jose import JsonWebKey, JsonWebToken, JWTClaims, KeySet, errors
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
        async with httpx.AsyncClient(timeout=30) as client:
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
            keys = jwks.as_dict()["keys"]
            # Extract algs and remove None
            algs = [item for item in tuple({key.get("alg") for key in keys}) if item is not None]
            if len(algs) > 1:
                logger.error("Multiple algorithms are not supported")
                raise Oauth2Error("Unable to decode the token with multiple algorithms")
            alg = algs[0]
            if not alg:
                raise Oauth2Error("Unable to decode the token with a missing algorithm")
            logger.debug(f"Algorithm used for decoding the token: {alg}")
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
        except KeyError:
            logger.error("Unable to find an algorithm in the key")
            raise Oauth2Error(  # noqa
                "Unable to decode the token with a missing algorithm"
            )
        except errors.ExpiredTokenError:
            logger.error("Unable to validate an expired token")
            raise Oauth2Error("Unable to validate an expired token")  # noqa
        except errors.JoseError:
            logger.error("Unable to decode token")
            raise Oauth2Error("Unable to decode token")  # noqa
        except Exception as e:
            logger.error(f"Generic decode exception: f{e}")
            raise e

        return claims

    async def authenticate(
        self,
        request: Request,
        accepted_methods: typing.List[str] = ["access_token"],  # noqa
    ) -> RedirectResponse | dict:
        """Authenticate the caller with the incoming request."""
        bearer = request.headers.get("Authorization")
        if not bearer:
            logger.exception("Unable to get a token")
            raise Oauth2Error("Auth token not found in the incoming request")
        access_token = bearer.replace("Bearer ", "")
        try:
            claims = await self.decode_token(access_token)
            if not claims:
                pass
            return claims
        except Exception:
            raise Oauth2Error("Authentication error")  # noqa
