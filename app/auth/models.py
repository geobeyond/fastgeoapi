"""Authentication models module."""

from openapi_pydantic.v3.v3_0_3 import Response

unauthorized = {
    "401": Response(description="Unauthorized response", message="Unauthenticated")
}
