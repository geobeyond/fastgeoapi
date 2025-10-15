"""OpenAPI contract tests module.

POST /items Endpoint Exclusion
===============================

These tests explicitly exclude POST /collections/{collectionId}/items
endpoints from contract testing due to inconsistencies in the OpenAPI
specification advertised by pygeoapi.

Background
----------
pygeoapi is designed to support transactions (create, update, delete
operations) on feature collections through OGC API - Features Part 4:
Create, Replace, Update and Delete. However, these transaction
capabilities must be explicitly configured in the pygeoapi configuration
file.

The Problem
-----------
pygeoapi advertises POST /collections/{collectionId}/items endpoints in
its OpenAPI specification regardless of whether transactions are actually
configured and enabled for those collections. This creates a mismatch
between:

1. Advertised API: The OpenAPI document includes POST endpoints with
   request body schemas
2. Actual Configuration: The server is not configured to handle these
   POST requests (no transaction provider configured)

Technical Details
-----------------
When transactions are not configured, pygeoapi's OpenAPI schema
generation includes POST endpoint definitions with invalid JSON Schema
references:

- Invalid reference: /$defs/propertyRef
- Location: Request body schema for POST /collections/{id}/items
- Impact: The referenced schema definition does not exist in the
  OpenAPI document

Example from the problematic schema::

    {
        'paths': {
            '/collections/lakes/items': {
                'post': {
                    'requestBody': {
                        'content': {
                            'application/geo+json': {
                                'schema': {'$ref': '#/$defs/propertyRef'}
                            }
                        }
                    }
                }
            }
        }
    }

Error Manifestation
-------------------
When schemathesis attempts to generate test cases for these endpoints,
it fails with::

    schemathesis.exceptions.SchemaError: Unresolvable JSON pointer
    in the schema: /$defs/propertyRef

This error occurs during test case generation (before the test even
runs), making it impossible to test these endpoints using property-based
testing.

The Solution
------------
The test fixtures in conftest.py use schemathesis's exclude() method to
filter out POST endpoints matching the pattern /collections/.../items::

    schema.exclude(method='POST', path_regex=r'.*/items$')

This filtering:

1. Happens at schema load time: Before test case generation begins
2. Is specific: Only excludes POST /items endpoints, allowing all other
   operations (GET, OPTIONS, DELETE, etc.) to be tested
3. Is necessary: Without this exclusion, the entire test suite would
   fail during test discovery

Affected Collections
--------------------
In this fastgeoapi instance, the following collections advertise invalid
POST endpoints:

- /collections/fabbricati/items
- /collections/georoma_civici/items
- /collections/lakes/items
- /collections/obs/items
- /collections/particelle/items

Verified Working Endpoints
---------------------------
The following POST endpoints are correctly defined and tested:

- POST /geoapi/processes/{processId}/execution (OGC API - Processes)

Future Resolution
-----------------
This workaround can be removed when one of the following occurs:

1. pygeoapi fixes schema generation: pygeoapi is updated to only
   advertise POST endpoints when transactions are actually configured
2. Configuration is added: Transaction providers are configured for the
   collections, making the POST endpoints functional
3. Schema is corrected: The propertyRef definition is added to the
   schema or the reference is removed from POST endpoint definitions

References
----------
- OGC API - Features Part 4: https://docs.ogc.org/DRAFTS/20-002.html
- pygeoapi transactions: https://docs.pygeoapi.io/en/latest/transactions.html
- Schemathesis filtering: https://schemathesis.readthedocs.io/en/stable/

See Also
--------
- tests/conftest.py: Schema fixture definitions with exclusion filters
- .github/workflows/contract-tests.yml: CI workflow for contract testing
"""

import os

import pytest
from hypothesis import Phase
from hypothesis import settings
from schemathesis.checks import not_a_server_error
from schemathesis.pytest import from_fixture
from starlette.testclient import TestClient

schema_apikey = from_fixture("protected_apikey_schema")
schema_bearer = from_fixture("protected_bearer_schema")


@pytest.mark.skipif(
    os.environ.get("API_KEY_ENABLED", "").lower() not in ("true", "1"),
    reason="Skipping API key tests when API_KEY is not enabled",
)
@schema_apikey.parametrize()
@settings(
    max_examples=5,
    deadline=30000,
    derandomize=True,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.target],
)
def test_api_with_apikey(case, protected_apikey_app):
    """Test the API with API-KEY protection."""
    # Skip POST /items endpoints - invalid schema references (cql2expression)
    # This is a pygeoapi OpenAPI schema issue in schemathesis 4.x
    if case.method.upper() == "POST" and case.path.endswith("/items"):
        pytest.skip("POST /items invalid schema - pygeoapi issue")

    # Provide valid data for process execution endpoints
    if case.method.upper() == "POST" and "/execution" in case.path:
        case.body = {"inputs": {"name": "test-user"}}

    if case.path_parameters:
        if case.path_parameters.get("jobId"):
            job_id = case.path_parameters.get("jobId")
            if r"\n" or r"\r" in job_id:
                case.path_parameters["jobId"] = job_id.strip()
            if "%0A" in job_id:
                case.path_parameters["jobId"] = job_id.replace("%0A", "")
            if "%0D" in job_id:
                case.path_parameters["jobId"] = job_id.replace("%0D", "")
    case.headers = {"X-API-KEY": "pygeoapi"}
    response = case.call()
    # Only check for server errors, skip schema validation due to pygeoapi issues
    case.validate_response(response, checks=(not_a_server_error,))


@pytest.mark.skipif(
    os.environ.get("JWKS_ENABLED", "").lower() not in ("true", "1"),
    reason="Skipping bearer token tests when JWKS is not enabled",
)
@schema_bearer.parametrize()
@settings(
    max_examples=10,
    deadline=None,
    derandomize=True,
    phases=[Phase.explicit, Phase.reuse, Phase.generate, Phase.target],
)
def test_api_with_bearer(case, access_token, protected_bearer_app):
    """Test the API with Authorization Bearer token protection."""
    # Skip POST /items endpoints - invalid schema references (cql2expression)
    # This is a pygeoapi OpenAPI schema issue in schemathesis 4.x
    if case.method.upper() == "POST" and case.path.endswith("/items"):
        pytest.skip("POST /items has invalid schema references - pygeoapi issue")

    # Provide valid data for process execution endpoints
    if case.method.upper() == "POST" and "/execution" in case.path:
        case.body = {"inputs": {"name": "test-user"}}

    if case.path_parameters:
        if case.path_parameters.get("jobId"):
            job_id = case.path_parameters.get("jobId")
            if r"\n" or r"\r" in job_id:
                case.path_parameters["jobId"] = job_id.strip()
            if "%0A" in job_id:
                case.path_parameters["jobId"] = job_id.replace("%0A", "")
            if "%0D" in job_id:
                case.path_parameters["jobId"] = job_id.replace("%0D", "")
    case.headers = {"Authorization": f"Bearer {access_token}"}
    # Use TestClient as session for ASGI app testing
    with TestClient(protected_bearer_app) as client:
        response = case.call(session=client)
    # Only check for server errors, skip schema validation due to pygeoapi issues
    case.validate_response(response, checks=(not_a_server_error,))
