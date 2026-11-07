"""Serve the example and the demo configuration for the OGC schema tests.

The schemas and the validator come from xpublish-ogc-core, which only the
``conformance`` dependency group installs. The test modules skip without
it, because pytest reports a skip raised while it loads a conftest as an
error.
"""

from dataclasses import dataclass
from pathlib import Path

import pytest
from starlette.testclient import TestClient

#: The configurations whose responses are validated, by test id. The
#: placeholders they use come from the suite's root conftest.
CONFIGURATIONS: dict[str, str] = {
    "example": "pygeoapi-config.yml",
    "demo": "pygeoapi-config.demo.yml",
}


@dataclass
class Served:
    """A configuration served in process.

    Attributes
    ----------
    client
        A client of the pygeoapi sub-app built from the configuration.
        Server errors come back as 500 responses instead of being raised.
    config
        The loaded configuration, placeholders resolved.
    """

    client: TestClient
    config: dict


def build_served(name: str) -> Served:
    """Build the sub-app of one configuration.

    The demo reads the schema of its remote Parquet datasets to build its
    OpenAPI document. When DuckDB cannot read that data, because the network
    fails or a release leaves the bucket, the cases of the configuration are
    skipped with the error as the reason and do not show up as schema
    violations.

    Parameters
    ----------
    name
        The id of the configuration in ``CONFIGURATIONS``.

    Returns
    -------
    Served
        The client and the configuration it serves.
    """
    import duckdb
    from pygeoapi.util import yaml_load

    from app.pygeoapi.factory import build_openapi, build_pygeoapi_subapp

    with Path(CONFIGURATIONS[name]).open() as handle:
        config = yaml_load(handle)
    try:
        openapi = build_openapi(config)
    except duckdb.IOException as error:
        pytest.skip(f"{name}: the data it names cannot be read ({error})")
    app = build_pygeoapi_subapp(config, openapi)
    return Served(client=TestClient(app, raise_server_exceptions=False), config=config)


@pytest.fixture(
    name="served", scope="module", params=list(CONFIGURATIONS), ids=list(CONFIGURATIONS)
)
def serve_configuration(request: pytest.FixtureRequest) -> Served:
    """Serve one configuration to the tests of a module.

    Parameters
    ----------
    request
        Carries the id of the configuration in ``CONFIGURATIONS``.

    Returns
    -------
    Served
        The client and the configuration it serves.
    """
    return build_served(request.param)
