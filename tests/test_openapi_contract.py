"""OpenAPI contract tests module."""

import os

import pytest
import schemathesis

schema_apikey = schemathesis.from_pytest_fixture("protected_apikey_schema")
schema_bearer = schemathesis.from_pytest_fixture("protected_bearer_schema")


@schema_apikey.parametrize()
def test_api_with_apikey(case):
    """Test the API with API-KEY protection."""
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
    case.validate_response(response)


@pytest.mark.skipif(
    os.environ.get("JWKS_ENABLED", "").lower() not in ("true", "1"),
    reason="Skipping bearer token tests when JWKS is not enabled",
)
@schema_bearer.parametrize()
def test_api_with_bearer(case, access_token):
    """Test the API with Authorization Bearer token protection."""
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
    response = case.call()
    case.validate_response(response)
