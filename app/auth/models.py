"""Authentication models module."""

import typing

import pydantic
from openapi_pydantic.v3.v3_0_3 import Response

unauthorized = {
    "401": Response(description="Unauthorized response", message="Unauthenticated")
}


class OAuth2Claim(pydantic.BaseModel):
    """Parse OAuth2 claims."""

    jti: str = pydantic.Field(...)
    sub: str = pydantic.Field(...)
    iat: int = pydantic.Field(...)
    exp: int = pydantic.Field(...)
    iss: str = pydantic.Field(...)
    aud: str = pydantic.Field(...)
    client_id: typing.Optional[str] = pydantic.Field(None)
