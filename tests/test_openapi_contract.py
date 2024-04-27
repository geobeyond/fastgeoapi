"""OpenAPI contract tests module."""

import schemathesis

schema = schemathesis.from_pytest_fixture("protected_apikey_schema")


@schema.parametrize()
def test_api(case):
    """Test the API with API-KEY protection."""
    case.headers = {"X-API-KEY": "pygeoapi"}
    response = case.call()
    case.validate_response(response)
