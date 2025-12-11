"""Authentication models module."""

import pydantic
from openapi_pydantic.v3.v3_0 import Response

unauthorized = {"401": Response(description="Unauthenticated")}


class OAuth2Claim(pydantic.BaseModel):
    """Parse OAuth2 claims."""

    jti: str = pydantic.Field(...)
    sub: str = pydantic.Field(...)
    iat: int = pydantic.Field(...)
    exp: int = pydantic.Field(...)
    iss: str = pydantic.Field(...)
    aud: str = pydantic.Field(...)
    client_id: str | None = pydantic.Field(None)


class TokenPayload(pydantic.BaseModel):
    """Parse payload to token endpoint."""

    grant_type: str = pydantic.Field(...)
    resource: str = pydantic.Field(...)
    scope: str = pydantic.Field(...)
