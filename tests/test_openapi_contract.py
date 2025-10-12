"""OpenAPI contract tests module."""

import pytest
import schemathesis


@pytest.fixture
def schema_apikey(protected_apikey_schema):
    """Get the API key schema."""
    return protected_apikey_schema


@pytest.fixture
def schema_bearer(protected_bearer_schema):
    """Get the bearer schema."""
    return protected_bearer_schema


@pytest.mark.schemathesis
def test_api_with_apikey(schema_apikey, case):
    """Test the API with API-KEY protection."""
    if case.path_parameters:
        if case.path_parameters.get('jobId'):
            job_id = case.path_parameters.get('jobId')
            if r'\n' or r'\r' in job_id:
                case.path_parameters['jobId'] = job_id.strip()
            if '%0A' in job_id:
                case.path_parameters['jobId'] = job_id.replace('%0A', '')
            if '%0D' in job_id:
                case.path_parameters['jobId'] = job_id.replace('%0D', '')
    case.headers = {'X-API-KEY': 'pygeoapi'}
    response = case.call()
    case.validate_response(response)


test_api_with_apikey = schemathesis.from_pytest_fixture(
    'schema_apikey'
).parametrize()(test_api_with_apikey)


@pytest.mark.schemathesis
def test_api_with_bearer(schema_bearer, case, access_token):
    """Test the API with Authorization Bearer token protection."""
    if case.path_parameters:
        if case.path_parameters.get('jobId'):
            job_id = case.path_parameters.get('jobId')
            if r'\n' or r'\r' in job_id:
                case.path_parameters['jobId'] = job_id.strip()
            if '%0A' in job_id:
                case.path_parameters['jobId'] = job_id.replace('%0A', '')
            if '%0D' in job_id:
                case.path_parameters['jobId'] = job_id.replace('%0D', '')
    case.headers = {'Authorization': f'Bearer {access_token}'}
    response = case.call()
    case.validate_response(response)


test_api_with_bearer = schemathesis.from_pytest_fixture(
    'schema_bearer'
).parametrize()(test_api_with_bearer)
