"""The configuration is checked against pygeoapi's schema before use.

pygeoapi ships a JSON Schema for its configuration and a
`validate_config` to apply it, and nothing in fastgeoapi ever called it.
That was tolerable when a configuration was a file someone edited before
restarting; ADR-0003 made it a document that arrives from a bucket and
is applied while the server runs.

Measured before writing any of this, on `build_openapi` +
`build_pygeoapi_subapp`:

- `resources` as a list  -> AttributeError: 'list' object has no attribute 'keys'
- a provider key typo    -> RuntimeError: name/type/data are required
- `server.bind` with no `port` -> **builds without complaining**

The first two are ugly errors far from their cause. The third is the one
that justifies the work: not an ugly error, an *absent* one.
"""

import copy

import pytest
from pygeoapi.util import yaml_load

from app.pygeoapi.factory import ConfigValidationError, normalize_config

CONFIG_PATH = "tests/data/pygeoapi-config.yml"


@pytest.fixture(scope="module")
def valid_config(pygeoapi_interpolation) -> dict:
    """The suite's configuration, expanded the way the app expands it."""
    with open(CONFIG_PATH) as handle:
        return yaml_load(handle)


@pytest.fixture(scope="module")
def pygeoapi_interpolation():
    """`${VAR}` placeholders need values before the document parses."""
    import os
    from unittest import mock

    variables = {
        "HOST": "0.0.0.0",
        "PORT": "5000",
        "PYGEOAPI_BASEURL": "http://localhost:5000",
        "FASTGEOAPI_CONTEXT": "/geoapi",
    }
    with mock.patch.dict(os.environ, variables, clear=False):
        yield variables


def test_a_configuration_without_bind_is_accepted(valid_config):
    """`server.bind` is required by the schema and read by nobody here.

    pygeoapi uses it in its own runners — `starlette_app.py:847`,
    `flask_app.py:671`, `django_app.py:57` — to bind a socket it opens
    itself. fastgeoapi never does: host and port come from
    `fastgeoapi run` and uvicorn. Verified by building the sub-app
    without it and serving the landing page, collections and items, all
    200.

    So refusing to start over it would be validation harming the people
    it is meant to protect: a working deployment stopped by a key that
    changes nothing. `normalize_config` fills it instead, with the
    values fastgeoapi actually binds.
    """
    without_bind = copy.deepcopy(valid_config)
    del without_bind["server"]["bind"]

    normalized = normalize_config(without_bind)

    assert normalized["server"]["bind"]["port"], normalized["server"]["bind"]


def test_a_structurally_broken_configuration_is_still_refused(valid_config):
    """The refusal has to keep biting where it earns its keep.

    `resources` as a list dies with `AttributeError: 'list' object has
    no attribute 'keys'`, far from the cause — that is what validation
    is for.
    """
    broken = copy.deepcopy(valid_config)
    broken["resources"] = ["lakes"]

    with pytest.raises(ConfigValidationError):
        normalize_config(broken)


def test_the_message_says_where_the_problem_is(valid_config):
    """An operator has to be able to find the key without a stack trace."""
    broken = copy.deepcopy(valid_config)
    broken["resources"] = ["lakes"]

    with pytest.raises(ConfigValidationError) as raised:
        normalize_config(broken)

    message = str(raised.value)
    assert "resources" in message
    assert "jsonschema" not in message.lower(), message


def test_a_valid_configuration_passes_through(valid_config):
    """Validation must not become a second place that rejects real setups."""
    normalized = normalize_config(copy.deepcopy(valid_config))

    assert normalized["server"]["limits"]["default_items"]
    assert set(normalized["resources"]) == {"obs", "lakes", "hello-world"}


def test_our_own_provider_options_are_not_rejected(valid_config):
    """The schema leaves provider keys open, and we rely on that.

    `store_options` and `engine_options` are ours, not pygeoapi's. They
    pass because `additionalProperties` is not declared on providers —
    if a schema update ever closed that door, this goes red and tells us
    before a deployment finds out.
    """
    extended = copy.deepcopy(valid_config)
    extended["resources"]["lakes"]["providers"][0]["store_options"] = {
        "region": "us-west-2",
        "skip_signature": True,
    }

    normalize_config(extended)


def test_startup_refuses_and_names_the_document(tmp_path, valid_config):
    """Fail-closed at boot, with enough to act on.

    Serving half a configuration is worse than not starting: the
    operator finds out from a user. But refusing is only useful if the
    message says *which* document and *which* key — a deployment may
    read its configuration from a bucket, and "port is required" alone
    does not say from where.
    """
    import copy
    import os
    import sys
    from unittest import mock

    import yaml

    # `resources` as a list: structurally wrong, and fatal far from the
    # cause. Not a missing `server.bind` — that one is filled, because
    # nothing in fastgeoapi reads it.
    invalid = copy.deepcopy(valid_config)
    invalid["resources"] = ["lakes"]
    target = tmp_path / "pygeoapi-config.yml"
    target.write_text(yaml.safe_dump(invalid))

    env = {
        "ENV_STATE": "dev",
        "DEV_PYGEOAPI_CONFIG": str(target),
        "DEV_PYGEOAPI_OPENAPI": "pygeoapi-openapi.yml",
        "DEV_FASTGEOAPI_WITH_MCP": "false",
        "DEV_API_KEY_ENABLED": "false",
        "DEV_JWKS_ENABLED": "false",
        "DEV_OPA_ENABLED": "false",
    }
    with mock.patch.dict(os.environ, env, clear=False):
        for key in [k for k in sys.modules if k.startswith("app.")]:
            del sys.modules[key]
        from app.config.app import FactoryConfig

        FactoryConfig.get_config.cache_clear()
        # After the purge this is a NEW class object: the one imported at
        # module level would not match what a freshly imported `main`
        # raises, and `pytest.raises` would let the error through.
        from app.pygeoapi.factory import ConfigValidationError as Fresh

        # Importing `main` IS the boot: the app is built at module level,
        # so this is where a deployment discovers the problem.
        with pytest.raises(Fresh) as raised:
            import app.main  # ruff: ignore[unused-import]

    message = str(raised.value)
    assert "resources" in message, message
    assert str(target) in message, message
