import pytest
import schemathesis


schema = schemathesis.from_pytest_fixture("protected_apikey_schema")

@schema.parametrize()
def test_api(case):
    case.headers = {"X-API-KEY": "pygeoapi"}
    response = case.call_asgi()
    case.validate_response(response)
