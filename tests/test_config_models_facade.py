"""Stable names in front of generated ones that can move.

`datamodel-code-generator` names collisions by position: `Provider`,
`Provider1`, `Provider2`. Which one is the *data* provider depends on
where it sits in the schema, so a reordering upstream renames things
without renaming anything — the import still resolves, the model still
validates, and it validates the wrong shape.

The facade is the only hand-written part of the models, and these tests
are what make it worth having: they check the alias points at a model
with the expected fields, not merely that the alias exists.
"""

import copy

import pytest
from pygeoapi.util import yaml_load

from app.pygeoapi.config_models import (
    ProviderDefinition,
    PygeoapiConfig,
    ResourceDefinition,
    ServerConfig,
)


def test_the_provider_alias_is_the_data_provider_not_the_organisation():
    """The alias most likely to be silently swapped.

    `Provider` in the generated module is the *metadata* provider — an
    organisation, with `name` and `url` — while the data provider is
    `Provider1`. Nothing but their order in the schema decides that.
    """
    fields = set(ProviderDefinition.model_fields)

    assert {"name", "type", "data"} <= fields, fields
    assert "url" not in fields, "this looks like the metadata provider, not the data one"


def test_the_resource_alias_carries_providers():
    """A resource is the thing that has providers and extents."""
    fields = set(ResourceDefinition.model_fields)

    assert {"type", "providers", "extents"} <= fields, fields


def test_the_server_alias_carries_bind_and_url():
    fields = set(ServerConfig.model_fields)

    assert {"bind", "url", "mimetype"} <= fields, fields


@pytest.fixture(scope="module")
def real_config() -> dict:
    with open("tests/data/pygeoapi-config.yml") as handle:
        return yaml_load(handle)


def test_the_models_accept_a_real_configuration(real_config):
    """Generation is worth nothing if the result rejects what we ship.

    Both configurations in the repository must pass — this one and the
    root document, which is what `pip install fastgeoapi` gets.
    """
    parsed = PygeoapiConfig.model_validate(copy.deepcopy(real_config))

    assert parsed.server.bind.port == 5000
    assert set(parsed.resources) == {"obs", "lakes", "hello-world"}


def test_the_models_accept_the_shipped_default():
    with open("pygeoapi-config.yml") as handle:
        PygeoapiConfig.model_validate(yaml_load(handle))


def test_our_own_provider_options_survive_validation(real_config):
    """`store_options` is ours, not pygeoapi's, and must not be dropped.

    The schema leaves provider keys open, so the models accept them —
    but a model that *accepts* and then *discards* would be worse than
    one that refused: the editor and stage 3 would silently lose them.
    """
    extended = copy.deepcopy(real_config)
    extended["resources"]["lakes"]["providers"][0]["store_options"] = {
        "region": "us-west-2",
        "skip_signature": True,
    }

    parsed = PygeoapiConfig.model_validate(extended)

    dumped = parsed.model_dump(by_alias=True, exclude_none=True)
    kept = dumped["resources"]["lakes"]["providers"][0]
    assert kept.get("store_options") == {"region": "us-west-2", "skip_signature": True}, kept
