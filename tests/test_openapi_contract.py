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
        "paths": {
            "/collections/lakes/items": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/geo+json": {"schema": {"$ref": "#/$defs/propertyRef"}}
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

    schema.exclude(method="POST", path_regex=r".*/items$")

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

- /collections/lakes/items
- /collections/obs/items

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
import schemathesis
from hypothesis import Phase, settings

# In schemathesis 4.x, filters must be applied on the LazySchema returned by from_fixture
# not on the schema inside the fixture
schema_apikey = (
    schemathesis.pytest.from_fixture("protected_apikey_schema")
    .exclude(method="POST", path_regex=r".*/items$")
    .exclude(method="OPTIONS")
)
schema_bearer = (
    schemathesis.pytest.from_fixture("protected_bearer_schema")
    .exclude(method="POST", path_regex=r".*/items$")
    .exclude(method="OPTIONS")
)


def not_unauthorized(ctx, response, case):
    """Fail the fuzz run on 401 Unauthorized for positive cases.

    A valid credential is always attached to positive cases: the bearer
    schema carries a schemathesis auth provider (conftest) and the
    API-key test sets the header explicitly. A 401 there means
    authentication broke — and without this check the run would pass
    vacuously, with every fuzzed request bouncing off the guard instead
    of reaching the API. Negative cases are exempt: schemathesis
    deliberately mutates security parameters (e.g. a garbage
    Authorization value, which the auth provider must not override),
    and rejecting those with a 401 is exactly the correct behaviour.
    """
    meta = case.meta
    if meta is not None and meta.generation.mode.is_negative:
        return None
    assert response.status_code != 401, "Unexpected 401: authentication is broken"


@pytest.mark.skipif(
    os.environ.get("API_KEY_ENABLED", "").lower() not in ("true", "1"),
    reason="Skipping API key tests when API_KEY is not enabled",
)
@schema_apikey.parametrize()
# deadline=None on purpose: these are integration-level contract tests —
# schemathesis itself recommends disabling hypothesis's per-example
# deadline for API tests, where response times are not deterministic
# (CI showed intermittent ~30s stalls that pass on replay, turning the
# deadline into a flake generator). Genuine hangs still fail through
# the test client's 30s transport timeout (conftest), as a ReadTimeout.
@settings(max_examples=50, deadline=None, phases=[Phase.generate])
def test_api_with_apikey(case):
    """Test the API with API-KEY protection."""
    # Provide valid data for process execution endpoints
    if case.method.upper() == "POST" and "/execution" in case.path:
        case.body = {"inputs": {"name": "test-user"}}

    if case.path_parameters and case.path_parameters.get("jobId"):
        job_id = case.path_parameters["jobId"]
        case.path_parameters["jobId"] = (
            job_id.replace("\n", "").replace("\r", "").replace("%0A", "").replace("%0D", "")
        )
    case.headers = {"X-API-KEY": "pygeoapi"}
    # response = case.call()
    # Only check for server errors, skip schema validation due to pygeoapi issues
    case.call_and_validate(checks=(schemathesis.checks.not_a_server_error, not_unauthorized))


@pytest.mark.skipif(
    os.environ.get("JWKS_ENABLED", "").lower() not in ("true", "1"),
    reason="Skipping bearer token tests when JWKS is not enabled",
)
@schema_bearer.parametrize()
# deadline=None on purpose: these are integration-level contract tests —
# schemathesis itself recommends disabling hypothesis's per-example
# deadline for API tests, where response times are not deterministic
# (CI showed intermittent ~30s stalls that pass on replay, turning the
# deadline into a flake generator). Genuine hangs still fail through
# the test client's 30s transport timeout (conftest), as a ReadTimeout.
@settings(max_examples=50, deadline=None, phases=[Phase.generate])
def test_api_with_bearer(case):
    """Test the API with Authorization Bearer token protection."""
    # Provide valid data for process execution endpoints
    if case.method.upper() == "POST" and "/execution" in case.path:
        case.body = {"inputs": {"name": "test-user"}}

    if case.path_parameters and case.path_parameters.get("jobId"):
        job_id = case.path_parameters["jobId"]
        case.path_parameters["jobId"] = (
            job_id.replace("\n", "").replace("\r", "").replace("%0A", "").replace("%0D", "")
        )
    # The Authorization header is attached by the schema-level auth
    # provider registered in conftest (schemathesis dynamic auth:
    # cached token, refetched and replayed on 401).
    # Only check for server errors, skip schema validation due to pygeoapi issues
    case.call_and_validate(checks=(schemathesis.checks.not_a_server_error, not_unauthorized))
