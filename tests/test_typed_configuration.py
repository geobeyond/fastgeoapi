"""Reading the configuration typed, without rebuilding it.

Stage 3 of ADR-0007. Our own code reads a Pydantic model; pygeoapi keeps
receiving the document exactly as it was loaded.

That split is not squeamishness. A `model_validate` → `model_dump` round
trip was measured before any of this was written, and it is **not
faithful**: 35 differences with the plain settings, 11 with the most
careful ones. The dangerous ones are gone at `mode="json",
exclude_unset=True` — generated enums do not derive from `str`, so
`Level.ERROR == "ERROR"` is false and pygeoapi compares strings in
eleven places; injected defaults would appear where an operator never
wrote them — but three `datetime -> str` remain, and pygeoapi does
arithmetic on those dates.

So the document is preserved, never regenerated. These tests pin that.
"""

import copy

import pytest
from pygeoapi.util import yaml_load

from app.pygeoapi.typed_config import TypedConfiguration

CONFIG_PATH = "tests/data/pygeoapi-config.yml"


@pytest.fixture(scope="module")
def document() -> dict:
    with open(CONFIG_PATH) as handle:
        return yaml_load(handle)


def test_the_document_handed_to_pygeoapi_is_the_one_that_was_read(document):
    """The invariant the whole stage rests on.

    If this ever goes red because someone rebuilt the document from the
    model, the failure it prevents is not a crash: it is a server that
    starts, serves, and quietly disagrees with its own configuration.
    """
    original = copy.deepcopy(document)

    typed = TypedConfiguration.of(document)

    assert typed.document == original
    assert typed.document is document, "the very object, not a copy of it"


def test_the_model_is_a_view_over_the_same_configuration(document):
    """Typed reading has to describe what is actually being served."""
    typed = TypedConfiguration.of(copy.deepcopy(document))

    assert set(typed.model.resources) == set(typed.document["resources"])
    assert typed.model.server.bind.port == typed.document["server"]["bind"]["port"]


def test_our_own_provider_options_are_readable_through_the_model(document):
    """`store_options` is ours, and stage 2 made the models keep it."""
    extended = copy.deepcopy(document)
    extended["resources"]["lakes"]["providers"][0]["store_options"] = {"region": "us-west-2"}

    typed = TypedConfiguration.of(extended)
    provider = typed.model.resources["lakes"].providers[0]

    assert getattr(provider, "store_options") == {"region": "us-west-2"}


def test_an_invalid_configuration_is_refused_at_the_boundary(document):
    """Stage 1's refusal must not be bypassed by the typed path.

    Both imports happen here, together. Another module purges `app.*`
    from `sys.modules` to exercise the boot path, so a class imported at
    collection time is a *different object* from the one a freshly
    imported module raises — and `pytest.raises` would let it through.
    """
    from app.pygeoapi.factory import ConfigValidationError
    from app.pygeoapi.typed_config import TypedConfiguration as Fresh

    # Structurally wrong, unlike a missing `server.bind`, which is
    # filled because nothing in fastgeoapi reads it.
    broken = copy.deepcopy(document)
    broken["resources"] = ["lakes"]

    with pytest.raises(ConfigValidationError):
        Fresh.of(broken)
