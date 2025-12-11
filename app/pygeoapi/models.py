"""pygeoapi models module."""

from openapi_pydantic.v3.v3_0 import Reference

not_found = {
    "404": Reference(
        **{
            "$ref": "https://schemas.opengis.net/ogcapi/features/part1/1.0/openapi/ogcapi-features-1.yaml#/components/responses/NotFound"
        }
    )
}
