"""OpenAPI contract tests module."""

import schemathesis

schema = schemathesis.from_pytest_fixture("protected_apikey_schema")


@schema.parametrize()
def test_api(case):
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
